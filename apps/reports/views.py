import json
import urllib.request
import urllib.error
import urllib.parse
import ssl
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from rest_framework_simplejwt.authentication import JWTAuthentication

logger = logging.getLogger(__name__)

# Admin Reports tab: Rejected rows stay visible only for this many days (by submitted_at).
REJECTED_REPORTS_ADMIN_VISIBILITY_DAYS = 7

from .models import Report
from .pagination import ReportPageNumberPagination
from .serializers import (
    ReportSerializer,
    ReportListSerializer,
    ReportCreateSerializer,
    ReportUpdateSerializer
)
from apps.admins.permissions import IsAdmin
from apps.admins.authentication import AdminJWTAuthentication
from apps.reports.services import citizen_submission as citizen_submit


# SSL context for networks with certificate issues
ssl_context = ssl. create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


class ReportViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Report CRUD operations
    """
    pagination_class = ReportPageNumberPagination
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]  # ✅ Support file uploads for admin panel
    queryset = Report.objects.select_related(
        'citizen_id',
        'worker_id',
        'worker_id__worker_id',
        'created_by_admin',
    ).prefetch_related('feedback').all()
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ReportListSerializer
        elif self.action == 'create': 
            return ReportCreateSerializer
        elif self.action in ['update', 'partial_update']: 
            return ReportUpdateSerializer
        return ReportSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        status_filter = self. request.query_params.get('status')
        if status_filter:
            queryset = queryset. filter(status=status_filter)
        
        worker_id = self.request. query_params.get('worker_id')
        if worker_id:
            queryset = queryset. filter(worker_id=worker_id)
        
        waste_type = self.request. query_params.get('waste_type')
        if waste_type:
            queryset = queryset. filter(waste_type=waste_type)

        report_source = self.request.query_params.get('report_source')
        if report_source in ('citizen', 'admin'):
            queryset = queryset.filter(report_source=report_source)
        
        search = self.request. query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(report_id__icontains=search)
                | (Q(citizen_id__isnull=False) & Q(citizen_id__name__icontains=search))
                | Q(created_by_admin__name__icontains=search)
            )
        
        date_from = self. request.query_params.get('date_from')
        date_to = self. request.query_params.get('date_to')
        if date_from: 
            queryset = queryset.filter(submitted_at__gte=date_from)
        if date_to:
            queryset = queryset. filter(submitted_at__lte=date_to)

        # Admin Reports tab list: hide rejected rows older than 7 days.
        if self.action == 'list':
            rejected_cutoff = timezone.now() - timedelta(
                days=REJECTED_REPORTS_ADMIN_VISIBILITY_DAYS
            )
            queryset = queryset.exclude(
                Q(status='Rejected') & Q(submitted_at__lt=rejected_cutoff)
            )
        
        ordering = self.request.query_params.get('ordering', 'report_id')
        allowed_orderings = {
            'report_id',
            '-report_id',
            'submitted_at',
            '-submitted_at',
        }
        if ordering not in allowed_orderings:
            ordering = 'report_id'
        queryset = queryset.order_by(ordering)
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        
        # ✅ Reset serializer cache for each request (fresh calculation)
        from .serializers import ReportListSerializer
        if self.get_serializer_class() == ReportListSerializer:
            ReportListSerializer._task_number_cache = {}
            ReportListSerializer._cache_initialized = False
        
        list_context = {'request': request, 'list_view': True}
        page = self.paginate_queryset(queryset)
        if page is not None: 
            serializer = self.get_serializer(page, many=True, context=list_context)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True, context=list_context)
        return Response({
            'success': True,
            'count': queryset.count(),
            'results': serializer.data
        })
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ReportSerializer(instance, context={'request': request})
        return Response({
            'success':  True,
            'data': serializer.data
        })
    
    @action(detail=False, methods=['post'], url_path='verify_waste_image')
    def verify_waste_image(self, request):
        """
        Admin-only: run YOLO (best.pt) on image before create-task submit.
        Does not save a report.
        """
        from .services import admin_waste_verification as admin_ai

        image_before = request.FILES.get('image_before') or request.FILES.get('image')
        try:
            verification = admin_ai.verify_admin_task_image(image_before)
        except ImportError:
            return Response({
                'success': False,
                'rejected': True,
                'message': 'ML model service unavailable. Install ultralytics and add model_ml/best.pt',
                'ai_result': 'Unverified',
                'ai_confidence': 0.0,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.error('Admin verify_waste_image failed: %s', exc, exc_info=True)
            return Response({
                'success': False,
                'rejected': True,
                'message': f'AI verification failed: {exc}',
                'ai_result': 'Unverified',
                'ai_confidence': 0.0,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if verification['passed']:
            return Response({
                'success': True,
                'rejected': False,
                'message': verification['message'],
                'ai_verification': verification['ai_verification'],
            }, status=status.HTTP_200_OK)

        body, code = admin_ai.build_rejection_response(verification)
        status_code = (
            status.HTTP_500_INTERNAL_SERVER_ERROR
            if verification.get('reason') == 'unverified'
            else status.HTTP_400_BAD_REQUEST
        )
        return Response(body, status=status_code)

    @action(detail=True, methods=['post'], url_path='verify_ai_detections')
    def verify_ai_detections(self, request, pk=None):
        """
        Admin report details: run YOLO on stored image_before (no image re-upload).
        Always returns ai_verification for UI overlays; does not change report status.
        """
        from .services import admin_waste_verification as admin_ai

        report = self.get_object()
        try:
            verification = admin_ai.verify_report_image(report)
        except ImportError:
            return Response({
                'success': False,
                'message': 'ML model service unavailable',
                'ai_verification': None,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.error('verify_ai_detections failed for report %s: %s', pk, exc, exc_info=True)
            return Response({
                'success': False,
                'message': f'AI detection failed: {exc}',
                'ai_verification': None,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        block = verification.get('ai_verification')
        return Response({
            'success': True,
            'rejected': not verification.get('passed'),
            'message': verification.get('message'),
            'ai_verification': block,
            'cached': bool(verification.get('cached')),
        }, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        """
        Create a new report (admin panel).
        Runs best.pt waste detection first; rejects if no waste / model error.
        """
        from .services import admin_waste_verification as admin_ai

        image_before = request.FILES.get('image_before') or request.FILES.get('image')

        location_address = request.data.get('location_address')
        if not location_address or not str(location_address).strip():
            return Response({
                'success': False,
                'message': 'location_address is required for admin task creation',
                'rejected': True,
            }, status=status.HTTP_400_BAD_REQUEST)

        if not image_before:
            return Response({
                'success': False,
                'message': 'image_before is required for AI verification',
                'ai_result': 'Unverified',
                'ai_confidence': 0.0,
                'rejected': True,
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            verification = admin_ai.verify_admin_task_image(image_before)
        except ImportError:
            return Response({
                'success': False,
                'message': 'ML model service unavailable. Please contact administrator.',
                'ai_result': 'Unverified',
                'rejected': True,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.error('Admin create AI verification error: %s', exc, exc_info=True)
            return Response({
                'success': False,
                'message': f'AI verification failed: {exc}',
                'ai_result': 'Unverified',
                'ai_confidence': 0.0,
                'rejected': True,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not verification['passed']:
            body, _ = admin_ai.build_rejection_response(verification)
            status_code = (
                status.HTTP_500_INTERNAL_SERVER_ERROR
                if verification.get('reason') == 'unverified'
                else status.HTTP_400_BAD_REQUEST
            )
            return Response(body, status=status_code)

        ml_result = verification['ml_result']
        logger.info(
            'Admin task create: waste detected (%s, confidence=%.2f)',
            ml_result.get('waste_type'),
            float(ml_result.get('ai_confidence') or 0),
        )

        if hasattr(image_before, 'seek'):
            image_before.seek(0)
        admin_ai.apply_ml_to_mutable_request_data(request, ml_result)

        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        report = serializer.save()

        detail_serializer = ReportSerializer(report, context={'request': request})
        return Response(
            admin_ai.build_create_success_response(report, detail_serializer, ml_result),
            status=status.HTTP_201_CREATED,
        )
    
    @action(detail=True, methods=['post'])
    def assign(self, request, pk=None):
        report = self.get_object()
        worker_id = request.data.get('worker_id')

        if not worker_id: 
            return Response(
                {'success': False, 'error': 'worker_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        from apps.workers.models import Worker
        try:
            worker = Worker.objects.get(worker_id=worker_id)
        except Worker.DoesNotExist: 
            return Response(
                {'success': False, 'error':  'Worker not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        report.worker_id = worker
        # Admin assignment should move task into worker pending bucket.
        report.status = 'Pending'
        # ✅ Clear accepted_at when admin assigns/reassigns
        report.accepted_at = None
        report.save(update_fields=['worker_id', 'status', 'accepted_at'])

        # ✅ Send notification to assigned worker (clearly labelled as from admin)
        try:
            from apps.notifications.models import Notification, RecipientType, NotificationStatus
            from apps.notifications.admin_worker_messages import (
                admin_display_name,
                build_admin_task_assignment_notification,
            )

            worker_display_name = (worker.worker_id.name or '').strip() or 'Worker'
            admin_name = admin_display_name(request.user)
            notification_title, notification_message = build_admin_task_assignment_notification(
                admin_name=admin_name,
                report=report,
                worker_display_name=worker_display_name,
            )

            notification = Notification.objects.create(
                recipient_type=RecipientType.WORKER,
                recipient_id=worker.worker_id.account_id,
                message=notification_message,
                is_read=False,
                title=notification_title,
                status=NotificationStatus.PENDING,
                expires_at=None,
                report_id=report.report_id,
            )
            
            logger.info(f'📤 Notification sent to worker {worker.employee_code} for assigned report #{report.report_id}')
        except Exception as e:
            logger.error(f'❌ Failed to send notification to worker: {str(e)}', exc_info=True)
            # Don't fail the assignment if notification fails

        return Response({
            'success': True,
            'message': 'Worker assigned successfully',
            'data':  ReportSerializer(report).data
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['patch'], url_path='update_status')
    def update_status(self, request, pk=None):
        report = self.get_object()
        new_status = request. data.get('status')

        if not new_status: 
            return Response(
                {'success': False, 'error':  'status is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        allowed_statuses = [
            'Pending', 'Assigned', 'In Progress', 'Resolved', 'Rejected'
        ]
        if new_status not in allowed_statuses:
            return Response(
                {'success': False, 'error': 'Invalid status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if new_status == 'Rejected':
            # Admin can reject only actionable states.
            if report.status not in ['Pending', 'Assigned', 'In Progress']:
                return Response(
                    {'success': False, 'error': f'Cannot reject report from "{report.status}" state'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Remove task from worker side immediately when rejected.
            report.status = 'Rejected'
            report.worker_id = None
            report.accepted_at = None
            report.started_at = None
            report.save(update_fields=['status', 'worker_id', 'accepted_at', 'started_at'])

            try:
                from apps.notifications.models import Notification, RecipientType, NotificationStatus

                citizen_account_id = getattr(report.citizen_id, 'account_id', None) or report.citizen_id_id
                if citizen_account_id:
                    Notification.objects.create(
                        recipient_type=RecipientType.CITIZEN,
                        recipient_id=citizen_account_id,
                        title='Report Rejected',
                        message=json.dumps({
                            'type': 'report_rejected',
                            'title': 'Report Rejected',
                            'report_id': report.report_id,
                            'message': f'Your report #{report.report_id} has been rejected by admin.',
                            'status': 'Rejected'
                        }),
                        status=NotificationStatus.PENDING,
                        is_read=False,
                        report_id=report.report_id
                    )
            except Exception as e:
                logger.error(f'Failed to notify citizen about rejection: {str(e)}', exc_info=True)

            return Response({
                'success': True,
                'message': 'Report rejected successfully',
                'data': ReportSerializer(report).data
            }, status=status.HTTP_200_OK)

        report.status = new_status
        # ✅ Set started_at when status changes to 'In Progress'
        if new_status == 'In Progress' and report.started_at is None:
            report.started_at = timezone.now()
            report.save(update_fields=['status', 'started_at'])
            
            # ✅ Send notification to citizen when work starts
            from apps.notifications.models import Notification, RecipientType
            import json

            citizen_name = (report.citizen_id.name or '').strip() if report.citizen_id else 'Citizen'
            wkr = report.worker_id
            worker_name = (
                (wkr.worker_id.name or '').strip()
                if wkr and wkr.worker_id
                else 'Worker'
            )
            waste_label = (report.waste_type or '').strip() or 'waste'

            if report.citizen_id:
                Notification.objects.create(
                    recipient_type=RecipientType.CITIZEN,
                    recipient_id=report.citizen_id.account_id,
                    message=json.dumps({
                        'type': 'work_started',
                        'title': 'Work Started',
                        'report_id': report.report_id,
                        'citizen_name': citizen_name,
                        'worker_name': worker_name,
                        'waste_type': waste_label,
                        'message': (
                            f'{citizen_name}, {worker_name} started work on your '
                            f'Report #{report.report_id} ({waste_label}).'
                        ),
                        'status': 'In Progress'
                    }),
                    is_read=False
                )
        else:
            report.save(update_fields=['status'])

        return Response({
            'success': True,
            'message': 'Status updated successfully',
            'data': ReportSerializer(report).data
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        total = Report.objects.count()
        pending = Report.objects. filter(status='Pending').count()
        assigned = Report. objects.filter(status='Assigned').count()
        in_progress = Report.objects.filter(status='In Progress').count()
        resolved = Report.objects.filter(status='Resolved').count()
        rejected = Report.objects. filter(status='Rejected').count()
        
        verified = Report.objects.filter(ai_result='Waste').count()
        unverified = Report. objects.filter(ai_result='Unverified').count()
        
        return Response({
            'success': True,
            'data': {
                'total': total,
                'by_status': {
                    'pending': pending,
                    'assigned': assigned,
                    'in_progress': in_progress,
                    'resolved': resolved,
                    'rejected': rejected
                },
                'by_ai_verification': {
                    'verified': verified,
                    'unverified': unverified
                }
            }
        })

    # ============================================
    # GEOCODING ENDPOINT - DETAILED STREET ADDRESS
    # ============================================
    @action(detail=False, methods=['get'])
    def geocode(self, request):
        """
        Reverse geocode coordinates to DETAILED street address
        GET /api/reports/geocode/? lat=31.67&lng=73.98
        
        Returns format like:
        - "New York City Hall, 260 Broadway, Tribeca, New York"
        - "Srinagar Highway, G-9/1, Islamabad, 44000"
        - "Ayya Virkan, Punjab, 39350"
        """
        try:
            lat = request.query_params.get('lat')
            lng = request.query_params.get('lng')
            
            if not lat or not lng: 
                return Response({
                    'success': False,
                    'error': 'lat and lng parameters are required'
                }, status=status. HTTP_400_BAD_REQUEST)
            
            lat = float(lat)
            lng = float(lng)
            
            print(f"\n📍 Geocoding:  {lat}, {lng}")
            
            address = None
            provider = None
            
            # Try Nominatim first (most detailed for street addresses)
            result = self._try_nominatim_detailed(lat, lng)
            if result: 
                address = result['address']
                provider = 'Nominatim'
            
            # Try BigDataCloud
            if not address: 
                result = self._try_bigdatacloud_detailed(lat, lng)
                if result: 
                    address = result['address']
                    provider = 'BigDataCloud'
            
            # Fallback to local database
            if not address:
                address = self._get_detailed_pakistan_location(lat, lng)
                provider = 'Local Database'
            
            print(f"✅ Result ({provider}): {address}\n")
            
            return Response({
                'success': True,
                'data': {
                    'address': address,
                    'lat': lat,
                    'lng': lng,
                    'provider': provider
                }
            })
            
        except ValueError:
            return Response({
                'success': False,
                'error': 'Invalid lat/lng values'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e: 
            print(f"❌ Geocode error: {e}")
            return Response({
                'success': True,
                'data': {
                    'address': self._get_detailed_pakistan_location(float(lat), float(lng)),
                    'lat': float(lat),
                    'lng': float(lng),
                    'provider': 'Fallback'
                }
            })

    @action(detail=False, methods=['get'])
    def geocode_address(self, request):
        """
        Forward geocode: address -> (lat,lng)
        GET /api/reports/geocode_address/?address=Madina%20Town%20Faisalabad
        """
        try:
            address = request.query_params.get('address')
            if not address or not str(address).strip():
                return Response({
                    'success': False,
                    'error': 'address parameter is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            address_str = str(address).strip()
            encoded = urllib.parse.quote(address_str)

            url = (
                'https://nominatim.openstreetmap.org/search'
                f'?format=jsonv2&limit=1&q={encoded}'
            )
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'NeatNowApp/1.0 (admin@neatnow.com)',
                    'Accept-Language': 'en',
                }
            )

            with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                data = json.loads(response.read().decode('utf-8'))

            if not data:
                return Response({
                    'success': False,
                    'error': 'Address not found'
                }, status=status.HTTP_404_NOT_FOUND)

            first = data[0]
            lat = float(first['lat'])
            lng = float(first['lon'])
            display_name = first.get('display_name') or address_str

            return Response({
                'success': True,
                'data': {
                    'address': display_name,
                    'lat': lat,
                    'lng': lng,
                    'provider': 'Nominatim',
                }
            })
        except Exception as e:
            logger.error(f'Geocode address error: {str(e)}', exc_info=True)
            return Response({
                'success': False,
                'error': 'Geocoding failed'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _make_request(self, url, headers=None, timeout=10):
        """Make HTTP request with proper error handling"""
        try:
            req = urllib.request. Request(url)
            if headers: 
                for key, value in headers.items():
                    req.add_header(key, value)
            
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as response:
                return json.loads(response. read().decode('utf-8'))
        except urllib.error.URLError as e: 
            print(f"   URL Error: {e}")
            return None
        except Exception as e:
            print(f"   Error: {e}")
            return None

    def _try_nominatim_detailed(self, lat, lng):
        """
        Nominatim - Returns detailed street address like:
        "New York City Hall, 260 Broadway, Tribeca, New York"
        """
        print("   Trying Nominatim (detailed)...")
        try:
            url = f"https://nominatim.openstreetmap.org/reverse? format=jsonv2&lat={lat}&lon={lng}&zoom=18&addressdetails=1"
            headers = {
                'User-Agent': 'NeatNowApp/1.0 (admin@neatnow.com)',
                'Accept-Language': 'en'
            }
            data = self._make_request(url, headers, timeout=10)
            
            if not data or 'address' not in data:
                return None
            
            addr = data['address']
            parts = []
            
            # 1. Building/Place name (landmark)
            building_name = (
                addr.get('building') or 
                addr.get('amenity') or 
                addr.get('tourism') or 
                addr.get('shop') or 
                addr.get('office') or
                addr.get('leisure') or
                addr.get('historic')
            )
            if building_name and building_name != 'yes':
                parts. append(building_name)
            
            # 2. House number + Road (street address)
            if addr.get('house_number') and addr.get('road'):
                parts.append(f"{addr['house_number']} {addr['road']}")
            elif addr.get('road'):
                parts. append(addr['road'])
            elif addr.get('pedestrian'):
                parts.append(addr['pedestrian'])
            elif addr.get('footway'):
                parts.append(addr['footway'])
            elif addr.get('highway'):
                parts. append(addr['highway'])
            
            # 3. Neighborhood/Suburb/Area
            neighborhood = (
                addr.get('neighbourhood') or 
                addr.get('suburb') or 
                addr.get('quarter') or
                addr.get('residential') or
                addr.get('hamlet')
            )
            if neighborhood: 
                parts.append(neighborhood)
            
            # 4. City/Town
            city = (
                addr. get('city') or 
                addr.get('town') or 
                addr.get('village') or
                addr.get('municipality') or
                addr.get('city_district')
            )
            if city:
                parts. append(city)
            
            # 5. Postal code (important for detailed address)
            postcode = addr.get('postcode')
            if postcode:
                parts.append(postcode)
            
            if parts:
                # Join all parts with comma
                result = ', '.join(parts)
                print(f"   ✓ Nominatim success: {result}")
                return {'address': result}
            
            # Fallback to display_name
            if data.get('display_name'):
                display_parts = data['display_name']. split(', ')[:5]
                result = ', '.join(display_parts)
                print(f"   ✓ Nominatim (display): {result}")
                return {'address': result}
                
        except Exception as e:
            print(f"   ✗ Nominatim failed: {e}")
        
        return None

    def _try_bigdatacloud_detailed(self, lat, lng):
        """
        BigDataCloud - Returns detailed address
        """
        print("   Trying BigDataCloud (detailed)...")
        try:
            url = f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lng}&localityLanguage=en"
            data = self._make_request(url)
            
            if not data: 
                return None
            
            parts = []
            
            # Street/Road
            if data.get('localityInfo') and data['localityInfo'].get('administrative'):
                admin = data['localityInfo']['administrative']
                for item in admin:
                    if item.get('adminLevel') == 10:  # Street level
                        parts. append(item.get('name', ''))
            
            # Locality (neighborhood)
            if data.get('locality'):
                parts.append(data['locality'])
            
            # City
            if data.get('city'):
                parts.append(data['city'])
            
            # State/Province
            if data.get('principalSubdivision'):
                parts.append(data['principalSubdivision'])
            
            # Postal code
            if data.get('postcode'):
                parts.append(data['postcode'])
            
            if parts: 
                result = ', '.join(parts)
                print(f"   ✓ BigDataCloud success: {result}")
                return {'address':  result}
                
        except Exception as e:
            print(f"   ✗ BigDataCloud failed: {e}")
        
        return None

    def _get_detailed_pakistan_location(self, lat, lng):
        """
        Detailed Pakistan locations with street/area names
        Returns format:  "Street/Area, City, Postal Code"
        """
        
        # ============================================
        # FAISALABAD (31.35 - 31.75, 72.95 - 74.15)
        # ============================================
        if 31.35 <= lat <= 31.75 and 72.95 <= lng <= 74.15:
            # Clock Tower / Ghanta Ghar
            if 31.415 <= lat <= 31.420 and 73.070 <= lng <= 73.080:
                return 'Clock Tower, Ghanta Ghar, Faisalabad, 38000'
            # D Ground
            if 31.410 <= lat <= 31.430 and 73.080 <= lng <= 73.100:
                return 'D Ground, Civil Lines, Faisalabad, 38000'
            # Peoples Colony
            if 31.430 <= lat <= 31.470 and 73.050 <= lng <= 73.100:
                return 'Peoples Colony No. 1, Faisalabad, 38000'
            # Madina Town
            if 31.450 <= lat <= 31.500 and 73.080 <= lng <= 73.150:
                return 'Madina Town, Faisalabad, 38000'
            # Susan Road
            if 31.480 <= lat <= 31.520 and 73.040 <= lng <= 73.100:
                return 'Susan Road, Faisalabad, 38000'
            # Gulberg
            if 31.440 <= lat <= 31.480 and 73.100 <= lng <= 73.160:
                return 'Gulberg Colony, Faisalabad, 38000'
            # Satiana Road
            if 31.380 <= lat <= 31.420 and 73.120 <= lng <= 73.180:
                return 'Satiana Road, Faisalabad, 38000'
            # Millat Town
            if 31.500 <= lat <= 31.550 and 73.080 <= lng <= 73.140:
                return 'Millat Town, Faisalabad, 38000'
            # Jinnah Colony
            if 31.400 <= lat <= 31.440 and 73.000 <= lng <= 73.060:
                return 'Jinnah Colony, Faisalabad, 38000'
            # Sammundri Road
            if 31.350 <= lat <= 31.400 and 73.050 <= lng <= 73.150:
                return 'Sammundri Road, Faisalabad, 38000'
            # Sargodha Road
            if 31.480 <= lat <= 31.550 and 73.000 <= lng <= 73.080:
                return 'Sargodha Road, Faisalabad, 38000'
            # Jhang Road
            if 31.420 <= lat <= 31.480 and 72.950 <= lng <= 73.020:
                return 'Jhang Road, Faisalabad, 38000'
            # Kotwali Road
            if 31.400 <= lat <= 31.430 and 73.060 <= lng <= 73.090:
                return 'Kotwali Road, Faisalabad, 38000'
            # Dijkot Road
            if 31.450 <= lat <= 31.500 and 73.020 <= lng <= 73.070:
                return 'Dijkot Road, Faisalabad, 38000'
            # General Faisalabad
            return f'Faisalabad, Punjab, 38000'
        
        # ============================================
        # ISLAMABAD (33.60 - 33.80, 72.80 - 73.20)
        # ============================================
        if 33.60 <= lat <= 33.80 and 72.80 <= lng <= 73.20:
            # Blue Area
            if 33.705 <= lat <= 33.715 and 73.055 <= lng <= 73.085:
                return 'Jinnah Avenue, Blue Area, Islamabad, 44000'
            # F-6
            if 33.720 <= lat <= 33.735 and 73.070 <= lng <= 73.090:
                return 'F-6 Markaz, Super Market, Islamabad, 44000'
            # F-7
            if 33.710 <= lat <= 33.725 and 73.055 <= lng <= 73.075:
                return 'F-7 Markaz, Jinnah Super, Islamabad, 44000'
            # G-9
            if 33.680 <= lat <= 33.700 and 73.025 <= lng <= 73.055:
                return 'Karachi Company, G-9, Islamabad, 44000'
            # G-10
            if 33.665 <= lat <= 33.685 and 73.010 <= lng <= 73.040:
                return 'G-10 Markaz, Islamabad, 44000'
            # G-11
            if 33.655 <= lat <= 33.675 and 72.995 <= lng <= 73.025:
                return 'G-11, Islamabad, 44000'
            # I-8
            if 33.670 <= lat <= 33.690 and 73.065 <= lng <= 73.095:
                return 'I-8 Markaz, Islamabad, 44000'
            # I-10
            if 33.645 <= lat <= 33.665 and 73.020 <= lng <= 73.050:
                return 'I-10, Islamabad, 44000'
            # E-11
            if 33.710 <= lat <= 33.730 and 73.005 <= lng <= 73.035:
                return 'E-11, Islamabad, 44000'
            # Srinagar Highway
            if 33.680 <= lat <= 33.720 and 73.030 <= lng <= 73.080:
                return f'Srinagar Highway, G-9/1, Islamabad, 44000'
            # General Islamabad
            return f'Islamabad, ICT, 44000'
        
        # ============================================
        # RAWALPINDI (33.55 - 33.70, 73.00 - 73.20)
        # ============================================
        if 33.55 <= lat <= 33.70 and 73.00 <= lng <= 73.20:
            # Saddar
            if 33.595 <= lat <= 33.610 and 73.045 <= lng <= 73.065:
                return 'Bank Road, Saddar, Rawalpindi, 46000'
            # Commercial Market
            if 33.580 <= lat <= 33.600 and 73.050 <= lng <= 73.070:
                return 'Commercial Market, Rawalpindi, 46000'
            # Satellite Town
            if 33.620 <= lat <= 33.650 and 73.050 <= lng <= 73.090:
                return 'Satellite Town, Rawalpindi, 46000'
            # Murree Road
            if 33.590 <= lat <= 33.620 and 73.055 <= lng <= 73.085:
                return 'Murree Road, Rawalpindi, 46000'
            return f'Rawalpindi, Punjab, 46000'
        
        # ============================================
        # LAHORE (31.40 - 31.65, 74.20 - 74.50)
        # ============================================
        if 31.40 <= lat <= 31.65 and 74.20 <= lng <= 74.50:
            # Gulberg
            if 31.510 <= lat <= 31.530 and 74.330 <= lng <= 74.360:
                return 'Main Boulevard, Gulberg III, Lahore, 54660'
            # DHA
            if 31.470 <= lat <= 31.510 and 74.380 <= lng <= 74.430:
                return 'Defence Housing Authority, Lahore, 54792'
            # Model Town
            if 31.480 <= lat <= 31.510 and 74.300 <= lng <= 74.340:
                return 'Model Town Link Road, Lahore, 54700'
            # Johar Town
            if 31.460 <= lat <= 31.490 and 74.290 <= lng <= 74.330:
                return 'Johar Town, Lahore, 54782'
            # Mall Road
            if 31.540 <= lat <= 31.560 and 74.300 <= lng <= 74.330:
                return 'Mall Road, Lahore, 54000'
            # Liberty Market
            if 31.510 <= lat <= 31.525 and 74.340 <= lng <= 74.360:
                return 'Liberty Market, Gulberg, Lahore, 54660'
            return f'Lahore, Punjab, 54000'
        
        # ============================================
        # KARACHI (24.80 - 25.00, 66.90 - 67.20)
        # ============================================
        if 24.80 <= lat <= 25.00 and 66.90 <= lng <= 67.20:
            # Clifton
            if 24.810 <= lat <= 24.830 and 67.020 <= lng <= 67.050:
                return 'Clifton Block 5, Karachi, 75600'
            # DHA
            if 24.790 <= lat <= 24.820 and 67.040 <= lng <= 67.080:
                return 'DHA Phase 6, Karachi, 75500'
            # Gulshan
            if 24.900 <= lat <= 24.930 and 67.070 <= lng <= 67.110:
                return 'Gulshan-e-Iqbal Block 13, Karachi, 75300'
            # Saddar
            if 24.850 <= lat <= 24.870 and 67.010 <= lng <= 67.040:
                return 'Saddar, Karachi, 74400'
            return f'Karachi, Sindh, 74000'
        
        # ============================================
        # General Pakistan regions
        # ============================================
        if 29.0 <= lat <= 37.0 and 60.0 <= lng <= 78.0:
            if lat >= 35.0:
                return f'Northern Areas, Pakistan'
            if 33.0 <= lat < 35.0:
                return f'Punjab/KPK Region, Pakistan'
            if 30.0 <= lat < 33.0:
                return f'Central Punjab, Pakistan'
            if lng <= 68.0:
                return f'Balochistan, Pakistan'
            return f'Sindh, Pakistan'
        
        # ============================================
        # USA - New York (for default coordinates)
        # ============================================
        if 40.5 <= lat <= 41.0 and -74.5 <= lng <= -73.5:
            # City Hall
            if 40.710 <= lat <= 40.715 and -74.010 <= lng <= -74.000:
                return 'New York City Hall, 260 Broadway, Tribeca, New York'
            # Times Square
            if 40.755 <= lat <= 40.760 and -73.990 <= lng <= -73.980:
                return 'Times Square, Broadway, Manhattan, New York'
            # Central Park
            if 40.765 <= lat <= 40.800 and -73.980 <= lng <= -73.950:
                return 'Central Park, Manhattan, New York'
            return 'Manhattan, New York, NY 10001'
        
        # Generic fallback
        return f'Location ({lat:. 4f}, {lng:. 4f})'


# ==================== CITIZEN REPORT ENDPOINTS ====================

class CitizenVerifyWasteImageView(APIView):
    """
    POST /api/reports/verify_citizen_image/
    Run backend YOLO (best.pt) on a citizen's image before/without saving a report.
    Same rules as admin: 20%+ single type OR mixed (2+ types at 20%+).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        from .services import admin_waste_verification as admin_ai

        user = request.user
        if not citizen_submit.is_citizen_user(user):
            return Response({
                'success': False,
                'message': 'Only citizens can verify images',
            }, status=status.HTTP_403_FORBIDDEN)

        image_before = request.FILES.get('image_before') or request.FILES.get('image')
        image_before = admin_ai.buffer_uploaded_image(image_before)
        try:
            verification = admin_ai.verify_citizen_waste_image(image_before)
        except ImportError:
            return Response({
                'success': False,
                'rejected': True,
                'message': 'ML model service unavailable. Please contact administrator.',
                'ai_result': 'Unverified',
                'ai_confidence': 0.0,
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Exception as exc:
            logger.error('Citizen verify_citizen_image failed: %s', exc, exc_info=True)
            return Response({
                'success': False,
                'rejected': True,
                'message': f'AI verification failed: {exc}',
                'ai_result': 'Unverified',
                'ai_confidence': 0.0,
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if verification['passed']:
            block = verification.get('ai_verification') or {}
            return Response({
                'success': True,
                'rejected': False,
                'message': verification['message'],
                'ai_result': block.get('ai_result', 'Waste'),
                'ai_confidence': block.get('ai_confidence', 0.0),
                'waste_type': block.get('waste_type'),
                'ai_verification': block,
            }, status=status.HTTP_200_OK)

        body, _code = admin_ai.build_rejection_response(verification)
        status_code = (
            status.HTTP_500_INTERNAL_SERVER_ERROR
            if verification.get('reason') == 'unverified'
            else status.HTTP_400_BAD_REQUEST
        )
        return Response(body, status=status_code)


class CitizenReportSubmissionView(APIView):
    """
    POST /api/reports/submit/
    Citizen report submission endpoint with image upload
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def post(self, request):
        """
        Submit a new report with image upload and ML verification.
        Optional: citizen_temp_id (client UUID) for offline sync idempotency.
        """
        try:
            user = request.user

            if not citizen_submit.is_citizen_user(user):
                return Response({
                    'success': False,
                    'message': 'Only citizens can submit reports'
                }, status=status.HTTP_403_FORBIDDEN)

            image_before = request.FILES.get('image_before') or request.FILES.get('image')
            latitude = request.data.get('latitude')
            longitude = request.data.get('longitude')
            waste_type = request.data.get('waste_type', '')
            citizen_temp_id = citizen_submit.normalize_citizen_temp_id(
                request.data.get('citizen_temp_id')
            )
            # Address shown in the app UI (geocoding / search) — stored as-is for accuracy.
            location_address = (
                request.data.get('location_address')
                or request.data.get('address')
                or ''
            )
            if isinstance(location_address, str):
                location_address = location_address.strip()[:2000]
            else:
                location_address = ''

            err = citizen_submit.validate_multipart_presence(image_before, latitude, longitude)
            if err:
                return Response({'success': False, 'message': err}, status=status.HTTP_400_BAD_REQUEST)

            from .services import admin_waste_verification as admin_ai

            image_before = admin_ai.buffer_uploaded_image(image_before)

            try:
                latitude, longitude = citizen_submit.parse_coordinate_pair(latitude, longitude)
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'message': 'Invalid GPS coordinates'
                }, status=status.HTTP_400_BAD_REQUEST)

            existing = citizen_submit.find_existing_by_temp_id(user, citizen_temp_id)
            if existing:
                serializer = ReportSerializer(existing, context={'request': request})
                return Response(
                    citizen_submit.build_submission_success_payload(
                        existing,
                        serializer,
                        message='Report already submitted (synced).',
                        final_waste_type=existing.waste_type,
                        ai_confidence=float(existing.ai_confidence or 0),
                    ),
                    status=status.HTTP_200_OK,
                )

            try:
                verification = admin_ai.verify_citizen_waste_image(image_before)
            except ImportError:
                return Response({
                    'success': False,
                    'message': 'ML model service unavailable. Please contact administrator.',
                    'ai_result': 'Unverified',
                    'rejected': True
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            except Exception as ml_error:
                import traceback
                logger.error('ML inference error: %s', str(ml_error))
                logger.error(traceback.format_exc())
                return Response({
                    'success': False,
                    'message': f'AI verification failed: {str(ml_error)}',
                    'ai_result': 'Unverified',
                    'ai_confidence': 0.0,
                    'rejected': True
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            if hasattr(image_before, 'seek'):
                image_before.seek(0)

            if not verification.get('passed'):
                body, _code = admin_ai.build_rejection_response(verification)
                reject_status = (
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                    if verification.get('reason') == 'unverified'
                    else status.HTTP_400_BAD_REQUEST
                )
                return Response(body, status=reject_status)

            ml_result = verification['ml_result']
            detected_waste_type = ml_result.get('waste_type')
            ai_confidence = ml_result.get('ai_confidence', 0.0)
            final_waste_type = detected_waste_type if detected_waste_type else (waste_type if waste_type else None)
            success_message = verification.get('message') or 'Report submitted successfully. AI verification passed.'

            report, created_new = citizen_submit.create_report_from_ml_safe(
                user,
                latitude=latitude,
                longitude=longitude,
                waste_type=waste_type,
                image_before=image_before,
                ml_result=ml_result,
                citizen_temp_id=citizen_temp_id,
                location_address=location_address or None,
            )

            if created_new:
                citizen_submit.notify_workers_for_report(report, user)

            serializer = ReportSerializer(report, context={'request': request})
            return Response(
                citizen_submit.build_submission_success_payload(
                    report,
                    serializer,
                    message=success_message,
                    final_waste_type=final_waste_type,
                    ai_confidence=float(ai_confidence),
                ),
                status=status.HTTP_201_CREATED,
            )

        except Exception as e:
            import traceback
            logger.error('Report submission error: %s', str(e))
            logger.error(traceback.format_exc())
            return Response({
                'success': False,
                'message': f'Failed to submit report: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CitizenMyReportsView(APIView):
    """
    GET /api/reports/my-reports/
    Get all reports submitted by the authenticated citizen
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    
    def get(self, request):
        """
        Get all reports for the authenticated citizen
        Query params:
        - status: Filter by status (Pending, Assigned, Resolved, etc.)
        """
        try:
            user = request.user
            
            # Check if user is a citizen
            if user.role != 'Citizen':
                return Response({
                    'success': False,
                    'message': 'Only citizens can view their reports'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Get reports for this citizen
            queryset = Report.objects.filter(citizen_id=user).order_by('-submitted_at')
            
            # Filter by status if provided
            status_filter = request.query_params.get('status')
            if status_filter:
                queryset = queryset.filter(status=status_filter)
            
            # Serialize reports (pass request context for image URLs)
            serializer = ReportListSerializer(queryset, many=True, context={'request': request})
            
            return Response({
                'success': True,
                'count': queryset.count(),
                'results': serializer.data
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Failed to fetch reports: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkerVerifyCleanupView(APIView):
    """
    POST /api/reports/worker-verify-cleanup/<report_id>/
    Compare image_before (citizen report) with uploaded image_after before resolving.
    Does not save the report — use worker-update-status to persist after pass.
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    parser_classes = [MultiPartParser, FormParser]

    def _get_worker(self, request):
        user = request.user
        if hasattr(user, 'account_id'):
            from apps.workers.models import Worker
            try:
                return Worker.objects.get(worker_id=user)
            except Worker.DoesNotExist:
                return None
        return None

    def post(self, request, report_id):
        from .services import similarity_cleanup as cleanup_ai
        from .services.admin_waste_verification import buffer_uploaded_image

        worker = self._get_worker(request)
        if not worker:
            return Response({
                'success': False,
                'error': 'Only workers can verify cleanup',
            }, status=status.HTTP_403_FORBIDDEN)

        try:
            report = Report.objects.get(report_id=report_id, worker_id=worker)
        except Report.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Report not found or not assigned to you',
            }, status=status.HTTP_404_NOT_FOUND)

        if report.status != 'In Progress':
            return Response({
                'success': False,
                'error': 'Report must be In Progress to verify cleanup',
            }, status=status.HTTP_400_BAD_REQUEST)

        image_after = (
            request.FILES.get('image_after')
            or request.FILES.get('verification_image')
            or request.FILES.get('image')
        )
        if not image_after:
            return Response({
                'success': False,
                'error': 'After cleanup image (image_after) is required',
            }, status=status.HTTP_400_BAD_REQUEST)

        image_after = buffer_uploaded_image(image_after)
        res_lat, res_lng = _parse_resolution_coordinates(request.data)
        verification = cleanup_ai.verify_worker_cleanup(
            report,
            image_after,
            resolution_latitude=res_lat,
            resolution_longitude=res_lng,
        )

        if verification.get('passed'):
            account_id = getattr(request.user, 'account_id', None) or getattr(
                request.user, 'pk', None,
            )
            if account_id is not None:
                cleanup_ai.mark_cleanup_verified(report.report_id, account_id)
            return Response(
                cleanup_ai.build_cleanup_success_response(verification),
                status=status.HTTP_200_OK,
            )

        body, code = cleanup_ai.build_cleanup_rejection_response(verification)
        return Response(body, status=code)


def _parse_resolution_coordinates(data):
    """Extract worker GPS from multipart/JSON body."""
    lat = data.get('resolution_latitude')
    lng = data.get('resolution_longitude')
    if lat is None or lng is None:
        return None, None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None


class WorkerUpdateReportStatusView(APIView):
    """
    Worker endpoint to update report status (for starting tasks and resolving with image)
    POST /api/reports/worker-update-status/<int:report_id>/
    Accepts:
    - status: 'In Progress' or 'Resolved'
    - image_after: (file, required for Resolved) After cleanup image
    - resolution_latitude: (float, optional) GPS latitude
    - resolution_longitude: (float, optional) GPS longitude
    - resolution_address: (string, optional) Address
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    parser_classes = [MultiPartParser, FormParser, JSONParser]  # ✅ Support file uploads
    
    def _get_worker(self, request):
        """Get worker from authenticated user"""
        user = request.user
        
        # Handle Account model
        if hasattr(user, 'account_id'):
            from apps.workers.models import Worker
            try:
                worker = Worker.objects.get(worker_id=user)
                return worker
            except Worker.DoesNotExist:
                return None
        
        return None
    
    def post(self, request, report_id):
        try:
            from apps.workers.models import Worker
            from apps.notifications.models import Notification, RecipientType
            import json
            
            # Debug: Print request info
            print(f'[WorkerUpdateReportStatusView] Received request for report_id={report_id}')
            print(f'[WorkerUpdateReportStatusView] User: {request.user}, Auth: {request.auth}')
            print(f'[WorkerUpdateReportStatusView] Request data keys: {request.data.keys() if hasattr(request.data, "keys") else "N/A"}')
            print(f'[WorkerUpdateReportStatusView] Files: {request.FILES.keys() if hasattr(request.FILES, "keys") else "N/A"}')
            
            # Get the worker
            worker = self._get_worker(request)
            if not worker:
                print(f'[WorkerUpdateReportStatusView] Worker not found for user: {request.user}')
                return Response({
                    'success': False,
                    'error': 'Only workers can update report status'
                }, status=status.HTTP_403_FORBIDDEN)
            
            print(f'[WorkerUpdateReportStatusView] Worker found: {worker.employee_code}')
            
            # Get the report
            try:
                report = Report.objects.select_related(
                    'citizen_id',
                    'created_by_admin',
                    'worker_id__worker_id',
                ).get(report_id=report_id, worker_id=worker)
                print(f'[WorkerUpdateReportStatusView] Report found: {report.report_id}, Status: {report.status}')
            except Report.DoesNotExist:
                print(f'[WorkerUpdateReportStatusView] Report {report_id} not found or not assigned to worker {worker.employee_code}')
                return Response({
                    'success': False,
                    'error': 'Report not found or not assigned to you'
                }, status=status.HTTP_404_NOT_FOUND)
            
            new_status = request.data.get('status')
            if not new_status:
                return Response({
                    'success': False,
                    'error': 'status is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            allowed_statuses = ['In Progress', 'Resolved']
            if new_status not in allowed_statuses:
                return Response({
                    'success': False,
                    'error': f'Invalid status. Allowed: {allowed_statuses}'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # ✅ Handle Resolved status with image_after
            if new_status == 'Resolved':
                from .services import similarity_cleanup as cleanup_ai
                from .services.admin_waste_verification import buffer_uploaded_image

                # ✅ After image is REQUIRED for Resolved status
                image_after = request.FILES.get('image_after') or request.FILES.get('verification_image') or request.FILES.get('image')
                if not image_after:
                    return Response({
                        'success': False,
                        'error': 'After cleanup image (image_after) is required for resolving a report'
                    }, status=status.HTTP_400_BAD_REQUEST)

                image_after = buffer_uploaded_image(image_after)
                resolution_lat, resolution_lng = _parse_resolution_coordinates(request.data)

                skip_dup_ai = str(
                    request.data.get('cleanup_verified', ''),
                ).lower() in ('1', 'true', 'yes')
                account_id = getattr(request.user, 'account_id', None) or getattr(
                    request.user, 'pk', None,
                )
                if skip_dup_ai and account_id is not None and cleanup_ai.is_cleanup_verified(
                    report.report_id, account_id,
                ):
                    verification = {'passed': True}
                else:
                    verification = cleanup_ai.verify_worker_cleanup(
                        report,
                        image_after,
                        resolution_latitude=resolution_lat,
                        resolution_longitude=resolution_lng,
                    )
                    if not verification.get('passed'):
                        body, code = cleanup_ai.build_cleanup_rejection_response(
                            verification,
                        )
                        return Response(body, status=code)
                    if account_id is not None:
                        cleanup_ai.mark_cleanup_verified(report.report_id, account_id)

                if hasattr(image_after, 'seek'):
                    image_after.seek(0)

                # Update image_after
                report.image_after = image_after
                
                # Update resolution location if provided (after validation used report site coords)
                if resolution_lat is not None and resolution_lng is not None:
                    report.latitude = resolution_lat
                    report.longitude = resolution_lng
                        
                
                # Update status and set resolved_at timestamp
                report.status = 'Resolved'
                report.resolved_at = timezone.now()  # ✅ Set resolved_at when report is resolved
                report.save(update_fields=['status', 'image_after', 'latitude', 'longitude', 'resolved_at'])
                
                # ✅ Update worker's lifetime stats (total_tasks and avg_rating)
                worker.update_stats()
                
                print(f'[WorkerUpdateReportStatusView] Report {report_id} resolved with after image')

                from .services.report_completion_notifications import notify_work_completed
                try:
                    notify_work_completed(report, worker)
                except Exception as notify_exc:
                    logger.error(
                        'Failed to send completion notification for report %s: %s',
                        report_id,
                        notify_exc,
                        exc_info=True,
                    )
            
            # ✅ Handle In Progress status
            elif new_status == 'In Progress':
                existing_in_progress = (
                    Report.objects.filter(
                        worker_id=worker,
                        status='In Progress',
                    )
                    .exclude(report_id=report_id)
                    .first()
                )
                if existing_in_progress:
                    return Response({
                        'success': False,
                        'error': 'already_in_progress',
                        'message': (
                            'There is already one report in progress. '
                            'Please resolve it before starting another task.'
                        ),
                        'active_report_id': existing_in_progress.report_id,
                    }, status=status.HTTP_409_CONFLICT)

                report.status = 'In Progress'
                
                # Set started_at when status changes to 'In Progress'
                if report.started_at is None:
                    report.started_at = timezone.now()
                    report.save(update_fields=['status', 'started_at'])
                    print(f'[WorkerUpdateReportStatusView] Status updated to In Progress, started_at set')
                else:
                    report.save(update_fields=['status'])
                
                from .services.report_completion_notifications import notify_work_started
                try:
                    notify_work_started(report, worker)
                except Exception as notify_exc:
                    logger.error(
                        'Failed to send work-started notification for report %s: %s',
                        report_id,
                        notify_exc,
                        exc_info=True,
                    )
            
            from .serializers import ReportListSerializer
            serializer = ReportListSerializer(report, context={'request': request})  # ✅ Pass request context for image URLs
            
            print(f'[WorkerUpdateReportStatusView] Successfully updated report {report_id} to {new_status}')
            return Response({
                'success': True,
                'message': 'Status updated successfully',
                'data': serializer.data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            import traceback
            error_msg = f'Error updating report status: {str(e)}\n{traceback.format_exc()}'
            print(f'[WorkerUpdateReportStatusView] {error_msg}')
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkerMyReportsView(APIView):
    """
    GET /api/reports/my-tasks/
    Get all reports assigned to the authenticated worker
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    
    def get(self, request):
        """
        Get all reports assigned to the authenticated worker
        Query params:
        - status: Filter by status (Pending, Assigned, In Progress, Resolved, etc.)
        """
        try:
            user = request.user
            
            # Get worker from authenticated user
            from apps.workers.models import Worker
            try:
                worker = Worker.objects.get(worker_id=user)
            except Worker.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Only workers can view their assigned reports'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Get reports assigned to this worker
            queryset = Report.objects.filter(worker_id=worker).order_by('-submitted_at')
            
            # Filter by status if provided
            status_filter = request.query_params.get('status')
            if status_filter:
                # ✅ For "Pending" tab, include both "Pending" and "Assigned" status
                # (Admin-assigned tasks have status='Assigned' but should appear in Pending tab)
                if status_filter.lower() == 'pending':
                    queryset = queryset.filter(status__in=['Pending', 'Assigned'])
                else:
                    queryset = queryset.filter(status=status_filter)
            
            # ✅ Reset serializer cache for each request (fresh calculation)
            from .serializers import ReportListSerializer
            ReportListSerializer._task_number_cache = {}
            ReportListSerializer._cache_initialized = False
            
            # Serialize reports
            serializer = ReportListSerializer(queryset, many=True, context={'request': request})
            
            return Response({
                'success': True,
                'count': queryset.count(),
                'data': serializer.data
            })
            
        except Exception as e:
            return Response({
                'success': False,
                'message': f'Failed to fetch reports: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkerMapSummaryView(APIView):
    """
    GET /api/reports/map-summary/
    Per-bucket counts for the worker map (same scope as my-tasks), aligned with
    Flutter map buckets: pending (includes Assigned + citizen-accepted pre-start), in_progress, resolved.
    Counts only reports with usable GPS (non-null lat/lng, both non-zero).
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        try:
            from apps.workers.models import Worker
            try:
                worker = Worker.objects.get(worker_id=request.user)
            except Worker.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Only workers can view map summary'
                }, status=status.HTTP_403_FORBIDDEN)

            qs = Report.objects.filter(worker_id=worker).exclude(status='Rejected')
            loc = qs.filter(
                latitude__isnull=False,
                longitude__isnull=False,
            ).exclude(latitude=0).exclude(longitude=0)

            # Split pending into two groups for map dots:
            # - admin_pending: assigned by admin and not accepted by worker yet
            # - citizen_pending: other not-started reports (citizen pending + accepted-not-started)
            admin_pending = loc.filter(
                status='Assigned',
                accepted_at__isnull=True,
            ).count()
            pending = loc.exclude(status__in=['In Progress', 'Resolved']).count()
            citizen_pending = max(pending - admin_pending, 0)
            in_progress = loc.filter(status='In Progress').count()
            resolved = loc.filter(status='Resolved').count()
            total = loc.count()

            return Response({
                'success': True,
                'counts': {
                    'all': total,
                    'pending': pending,
                    'admin_pending': admin_pending,
                    'citizen_pending': citizen_pending,
                    'in_progress': in_progress,
                    'resolved': resolved,
                },
            })
        except Exception as e:
            return Response({
                'success': False,
                'message': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== WORKER REPORT ACCEPT/DECLINE ENDPOINT ====================

class WorkerAcceptDeclineReportView(APIView):
    """
    POST /api/reports/accept-decline/<report_id>/
    Worker can accept or decline a report within 60 minutes
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    
    def _get_worker(self, request):
        """Get worker from authenticated user"""
        user = request.user
        
        # Handle Account model
        if hasattr(user, 'account_id'):
            from apps.workers.models import Worker
            try:
                worker = Worker.objects.get(worker_id=user)
                return worker
            except Worker.DoesNotExist:
                return None
        
        return None
    
    def post(self, request, report_id):
        """
        Accept or decline a report
        Body: {
            "action": "accept" or "decline"
        }
        """
        try:
            # Get worker
            worker = self._get_worker(request)
            if not worker:
                return Response({
                    'success': False,
                    'message': 'Only workers can accept/decline reports'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Get action
            action = request.data.get('action', '').lower()
            if action not in ['accept', 'decline']:
                return Response({
                    'success': False,
                    'message': 'Action must be "accept" or "decline"'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get report
            try:
                report = Report.objects.get(report_id=report_id)
            except Report.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Report not found'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Check if report is still pending
            if report.status != 'Pending':
                return Response({
                    'success': False,
                    'message': f'Report is already {report.status.lower()}. Cannot accept/decline.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if 60 minutes have passed
            time_elapsed = timezone.now() - report.submitted_at
            if time_elapsed > timedelta(minutes=60):
                return Response({
                    'success': False,
                    'message': 'Time limit exceeded. Cannot accept/decline after 60 minutes.'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if report is already assigned to another worker
            if report.worker_id and report.worker_id != worker:
                return Response({
                    'success': False,
                    'message': 'Report is already assigned to another worker'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if action == 'accept':
                # Assign report to worker
                report.worker_id = worker
                # ✅ Status 'Assigned' set karo (citizen ke liye), lekin worker ko 'Pending' return karo
                # Worker side mein 'Assigned' status ko 'Pending' treat kiya jayega
                report.status = 'Assigned'
                report.accepted_at = timezone.now()  # ✅ Set accepted_at timestamp for timer start
                report.save()
                
                # Mark notification as read and update status for this worker
                from apps.notifications.models import Notification, RecipientType, NotificationStatus
                import json
                
                # ✅ Calculate task number based on acceptance order for this worker (BEFORE updating notification)
                # Get all accepted reports for this worker (exclude declined/rejected)
                accepted_reports = Report.objects.filter(
                    worker_id=worker,
                    accepted_at__isnull=False,
                    status__in=['Assigned', 'In Progress', 'Resolved']
                ).order_by('accepted_at')
                
                # Find the index of this report (1-based)
                task_number = None
                for index, accepted_report in enumerate(accepted_reports, start=1):
                    if accepted_report.report_id == report.report_id:
                        task_number = index
                        break
                
                # Find and update related notification
                notifications = Notification.objects.filter(
                    recipient_type=RecipientType.WORKER,
                    recipient_id=worker.worker_id.account_id,
                    report_id=report_id  # ✅ Use direct report_id field
                )
                
                for notification in notifications:
                    # ✅ Update notification status and fields
                    notification.is_read = True
                    notification.status = NotificationStatus.ACCEPTED
                    notification.task_number = task_number
                    notification.accepted_at = report.accepted_at
                    # Update title if needed
                    if not notification.title or notification.title == 'Notification':
                        notification.title = f'Task Accepted - Report #{report_id}'
                    notification.save(update_fields=['is_read', 'status', 'task_number', 'accepted_at', 'title'])
                    break
                
                # Send notification to citizen (citizen-submitted reports only)
                if report.citizen_id:
                    Notification.objects.create(
                        recipient_type=RecipientType.CITIZEN,
                        recipient_id=report.citizen_id.account_id,
                        message=json.dumps({
                            'type': 'report_assigned',
                            'title': 'Worker Assigned',  # ✅ Add title for frontend
                            'report_id': report.report_id,
                            'worker_name': worker.worker_id.name,
                            'message': f'Report #{report.report_id} has been assigned to {worker.worker_id.name}',
                            'status': 'Assigned'
                        }),
                        is_read=False
                    )
                
                return Response({
                    'success': True,
                    'message': 'Report accepted successfully',
                    'data': {
                        'report_id': report.report_id,
                        'status': 'Pending',  # Worker sees as Pending (frontend will map 'Assigned' to 'Pending')
                        'assigned_to': worker.worker_id.name,
                        'task_number': task_number,  # ✅ Task number based on acceptance order
                        'accepted_at': report.accepted_at.isoformat() if report.accepted_at else None,
                        'timer_started': True
                    }
                }, status=status.HTTP_200_OK)
            
            else:  # decline
                # Mark notification as read and update status for this worker
                from apps.notifications.models import Notification, RecipientType, NotificationStatus
                import json
                
                notifications = Notification.objects.filter(
                    recipient_type=RecipientType.WORKER,
                    recipient_id=worker.worker_id.account_id,
                    report_id=report_id  # ✅ Use direct report_id field
                )
                
                for notification in notifications:
                    # ✅ Update notification status and fields
                    notification.is_read = True
                    notification.status = NotificationStatus.DECLINED
                    notification.title = 'Task Declined'
                    notification.save(update_fields=['is_read', 'status', 'title'])
                    break
                
                return Response({
                    'success': True,
                    'message': 'Report declined',
                    'data': {
                        'report_id': report.report_id,
                        'status': 'Pending'  # Still pending, waiting for other workers
                    }
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            import traceback
            print(f'❌ Accept/Decline error: {str(e)}')
            print(traceback.format_exc())
            return Response({
                'success': False,
                'message': f'Failed to process request: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
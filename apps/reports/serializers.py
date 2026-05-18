from rest_framework import serializers

from apps.accounts.models import Account

from .models import Report
import json
import urllib.request
import urllib.error
import ssl
from datetime import timedelta
from django.utils import timezone

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Simple location cache (in-memory)
_location_cache = {}


def get_location_from_coordinates(lat, lng):
    """
    Convert coordinates to readable address
    """
    if lat is None or lng is None:
        return 'Unknown Location'
    
    try:
        lat = float(lat)
        lng = float(lng)
    except (ValueError, TypeError):
        return 'Unknown Location'
    
    cache_key = f"{lat:.6f},{lng:.6f}"
    
    # Check cache
    if cache_key in _location_cache: 
        return _location_cache[cache_key]
    
    address = None
    
    # Try Nominatim
    try:
        url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lng}&zoom=18&addressdetails=1"
        req = urllib.request. Request(
            url,
            headers={
                'User-Agent': 'NeatNowApp/1.0',
                'Accept-Language': 'en'
            }
        )
        
        with urllib.request.urlopen(req, timeout=5, context=ssl_context) as response:
            data = json. loads(response.read().decode('utf-8'))
            
            if 'address' in data:
                addr = data['address']
                parts = []
                
                # Building/Landmark
                building = addr.get('building') or addr.get('amenity') or addr.get('tourism')
                if building and building != 'yes':
                    parts.append(building)
                
                # Street
                if addr.get('house_number') and addr.get('road'):
                    parts.append(f"{addr['house_number']} {addr['road']}")
                elif addr.get('road'):
                    parts.append(addr['road'])
                
                # Neighborhood
                neighborhood = addr.get('neighbourhood') or addr.get('suburb') or addr.get('quarter')
                if neighborhood:
                    parts.append(neighborhood)
                
                # City
                city = addr.get('city') or addr.get('town') or addr.get('village')
                if city:
                    parts.append(city)
                
                # Postal code
                if addr.get('postcode'):
                    parts.append(addr['postcode'])
                
                if parts:
                    address = ', '.join(parts)
    except Exception as e: 
        print(f"Nominatim error:  {e}")
    
    # Try BigDataCloud as fallback
    if not address:
        try:
            url = f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lng}&localityLanguage=en"
            req = urllib. request.Request(url)
            
            with urllib.request.urlopen(req, timeout=5, context=ssl_context) as response:
                data = json. loads(response.read().decode('utf-8'))
                
                parts = []
                if data.get('locality'):
                    parts.append(data['locality'])
                if data.get('city'):
                    parts.append(data['city'])
                if data.get('principalSubdivision'):
                    parts.append(data['principalSubdivision'])
                if data. get('postcode'):
                    parts.append(data['postcode'])
                
                if parts:
                    address = ', '.join(parts)
        except Exception as e: 
            print(f"BigDataCloud error:  {e}")
    
    # Local fallback for Pakistan/USA
    if not address: 
        address = get_local_fallback(lat, lng)
    
    # Cache the result
    _location_cache[cache_key] = address
    
    return address


def resolve_report_location_display(report) -> str:
    """
    Same readable string as ReportSerializer / ReportListSerializer `location`.
    Prefer citizen-submitted address; else reverse-geocode coordinates.
    """
    if getattr(report, 'location_address', None) and str(report.location_address).strip():
        return str(report.location_address).strip()
    return get_location_from_coordinates(
        getattr(report, 'latitude', None),
        getattr(report, 'longitude', None),
    )


def _is_generic_fallback_label(label: str) -> bool:
    """City-only offline labels — map UI should reverse-geocode for street detail."""
    t = (label or '').strip()
    if not t or t in ('Unknown Area', 'Unknown Location'):
        return True
    if t.lower().endswith(' region'):
        return True
    return t.lower() in {
        'lahore, punjab, 54000',
        'faisalabad, punjab, 38000',
        'islamabad, ict, 44000',
        'karachi, sindh, 74000',
        'lahore, punjab',
        'faisalabad, punjab',
    }


def resolve_report_location_display_list(report) -> str:
    """
    Fast path for list endpoints — never calls external geocoding APIs.
    Uses in-memory geocode cache when available.
    """
    addr = ''
    if getattr(report, 'location_address', None) and str(report.location_address).strip():
        addr = str(report.location_address).strip()
        if not _is_generic_fallback_label(addr):
            return addr
    lat = getattr(report, 'latitude', None)
    lng = getattr(report, 'longitude', None)
    if lat is not None and lng is not None:
        try:
            lat_f = float(lat)
            lng_f = float(lng)
            cache_key = f"{lat_f:.6f},{lng_f:.6f}"
            if cache_key in _location_cache:
                return _location_cache[cache_key]
            return get_local_fallback(lat_f, lng_f)
        except (TypeError, ValueError):
            pass
    return addr or 'Unknown Location'


def get_local_fallback(lat, lng):
    """Get location from local database for common areas"""
    
    # Faisalabad
    if 31.35 <= lat <= 31.75 and 72.95 <= lng <= 74.15:
        if 31.410 <= lat <= 31.430 and 73.080 <= lng <= 73.100:
            return 'D Ground, Civil Lines, Faisalabad, 38000'
        if 31.430 <= lat <= 31.470 and 73.050 <= lng <= 73.100:
            return 'Peoples Colony, Faisalabad, 38000'
        if 31.450 <= lat <= 31.500 and 73.080 <= lng <= 73.150:
            return 'Madina Town, Faisalabad, 38000'
        return 'Faisalabad, Punjab, 38000'
    
    # Islamabad
    if 33.60 <= lat <= 33.80 and 72.80 <= lng <= 73.20:
        if 33.680 <= lat <= 33.720 and 73.030 <= lng <= 73.080:
            return 'Srinagar Highway, G-9, Islamabad, 44000'
        if 33.705 <= lat <= 33.715 and 73.055 <= lng <= 73.085:
            return 'Blue Area, Islamabad, 44000'
        return 'Islamabad, ICT, 44000'
    
    # Lahore
    if 31.40 <= lat <= 31.65 and 74.20 <= lng <= 74.50:
        if 31.510 <= lat <= 31.530 and 74.330 <= lng <= 74.360:
            return 'Gulberg III, Lahore, 54660'
        return 'Lahore, Punjab, 54000'
    
    # Karachi
    if 24.80 <= lat <= 25.00 and 66.90 <= lng <= 67.20:
        return 'Karachi, Sindh, 74000'
    
    # New York
    if 40.5 <= lat <= 41.0 and -74.5 <= lng <= -73.5:
        if 40.710 <= lat <= 40.715 and -74.010 <= lng <= -74.000:
            return 'New York City Hall, 260 Broadway, Tribeca, New York'
        if 40.755 <= lat <= 40.760: 
            return 'Times Square, Manhattan, New York'
        return 'Manhattan, New York, NY 10001'
    
    return 'Unknown Area'


class ReportSerializer(serializers.ModelSerializer):
    """Full report serializer with computed fields"""
    citizen_name = serializers.SerializerMethodField()
    worker_name = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()  # ✅ Computed location
    feedback = serializers.SerializerMethodField()  # ✅ Include feedback data
    is_unassigned = serializers.SerializerMethodField()
    high_alert = serializers.SerializerMethodField()
    ai_categories = serializers.SerializerMethodField()
    
    class Meta: 
        model = Report
        fields = [
            'report_id',
            'report_source',
            'citizen_id',
            'created_by_admin_id',
            'citizen_name',
            'worker_name',
            'status',
            'ai_result',
            'waste_type',
            'ai_confidence',
            'ai_categories',
            'latitude',
            'longitude',
            'location_address',
            'location',  # ✅ Readable address (prefers location_address)
            'image_before',
            'image_after',
            'submitted_at',
            'assigned_at',
            'accepted_at',  # ✅ When worker accepts the report
            'started_at',  # ✅ When worker starts the task (status changes to In Progress)
            'resolved_at',
            'feedback',  # ✅ Feedback data (rating, comment)
            'is_unassigned',
            'high_alert',
        ]

    created_by_admin_id = serializers.IntegerField(read_only=True, allow_null=True)
    
    def get_citizen_name(self, obj):
        if getattr(obj, 'report_source', 'citizen') == 'admin':
            adm = getattr(obj, 'created_by_admin', None)
            if adm and getattr(adm, 'name', None):
                return adm.name
            return 'Admin'
        if obj.citizen_id:
            return obj.citizen_id.name
        return 'Unknown'
    
    def get_worker_name(self, obj):
        if obj.worker_id and hasattr(obj.worker_id, 'worker_id') and obj.worker_id.worker_id:
            return obj.worker_id. worker_id. name
        return None
    
    def get_location(self, obj):
        """Prefer citizen-submitted address; else reverse-geocode coordinates."""
        return resolve_report_location_display(obj)
    
    def get_feedback(self, obj):
        """Get feedback data for this report"""
        try:
            # Use related_name 'feedback' from Feedback model's OneToOneField
            if hasattr(obj, 'feedback') and obj.feedback:
                return {
                    'rating': obj.feedback.rating,
                    'comment': obj.feedback.comment,
                    'created_at': obj.feedback.created_at.isoformat() if obj.feedback.created_at else None,
                }
        except Exception:
            pass
        return None

    def get_is_unassigned(self, obj):
        from apps.reports.status_buckets import is_citizen_unassigned_expired
        return is_citizen_unassigned_expired(obj)

    def get_high_alert(self, obj):
        from apps.reports.status_buckets import is_citizen_unassigned_expired
        if not is_citizen_unassigned_expired(obj) or not obj.submitted_at:
            return False
        return (timezone.now() - obj.submitted_at) > timedelta(hours=48)

    def get_ai_categories(self, obj):
        from apps.reports.services.ai_categories import resolve_report_ai_categories
        return resolve_report_ai_categories(obj)


class ReportListSerializer(serializers. ModelSerializer):
    """Lightweight serializer for list view with optimized task number calculation"""
    citizen_name = serializers.SerializerMethodField()
    worker_name = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()  # ✅ Computed location
    task_number = serializers.SerializerMethodField()  # ✅ Task number based on acceptance order (optimized)
    after_image_url = serializers.SerializerMethodField()  # ✅ Convert image_after to after_image_url for frontend
    feedback = serializers.SerializerMethodField()  # ✅ Include feedback data
    reported_by = serializers.SerializerMethodField()  # ✅ Show "Reported by Citizen" or "Assigned by Admin"
    is_unassigned = serializers.SerializerMethodField()
    high_alert = serializers.SerializerMethodField()
    ai_categories = serializers.SerializerMethodField()
    ai_confidence = serializers.DecimalField(
        max_digits=3,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    
    # ✅ Class-level cache for task numbers (shared across all instances in a request)
    _task_number_cache = {}
    _cache_initialized = False
    
    class Meta: 
        model = Report
        fields = [
            'report_id',
            'report_source',
            'citizen_id',
            'created_by_admin_id',
            'citizen_name',
            'worker_name',
            'status',
            'ai_result',
            'waste_type',
            'ai_confidence',
            'ai_categories',
            'latitude',
            'longitude',
            'location_address',
            'location',  # ✅ Readable address (prefers location_address)
            'image_before',
            'image_after',  # ✅ After cleanup image (required for resolved reports) - kept for backward compatibility
            'after_image_url',  # ✅ Frontend-friendly field name
            'submitted_at',
            'accepted_at',  # ✅ When worker accepts the report
            'started_at',  # ✅ When worker starts the task (status changes to In Progress)
            'resolved_at',  # ✅ When report is resolved
            'task_number',  # ✅ Task number (1, 2, 3... based on acceptance order)
            'feedback',  # ✅ Feedback data (rating, comment)
            'reported_by',  # ✅ "Reported by Citizen" or "Assigned by Admin"
            'is_unassigned',
            'high_alert',
        ]

    created_by_admin_id = serializers.IntegerField(read_only=True, allow_null=True)
    
    def get_citizen_name(self, obj):
        if getattr(obj, 'report_source', 'citizen') == 'admin':
            adm = getattr(obj, 'created_by_admin', None)
            if adm and getattr(adm, 'name', None):
                return adm.name
            return 'Admin'

        # ✅ Admin assigned citizen report to worker without worker accept yet (legacy display)
        if obj.accepted_at is None and obj.status == 'Assigned' and obj.worker_id is not None:
            request = self.context.get('request') if hasattr(self, 'context') and self.context else None
            if request and hasattr(request, 'user'):
                from apps.admins.models import Admin
                if isinstance(request.user, Admin) and hasattr(request.user, 'name'):
                    return request.user.name
            return 'Admin'

        # Legacy rows: placeholder citizen account_id 1 before migration
        request = self.context.get('request') if hasattr(self, 'context') and self.context else None
        if request and hasattr(request, 'user'):
            from apps.admins.models import Admin
            if (
                isinstance(request.user, Admin)
                and obj.citizen_id
                and obj.citizen_id.account_id == 1
            ):
                if hasattr(request.user, 'name'):
                    return request.user.name

        if obj.citizen_id:
            return obj.citizen_id.name
        return 'Unknown'
    
    def get_worker_name(self, obj):
        if obj.worker_id and hasattr(obj.worker_id, 'worker_id') and obj.worker_id.worker_id:
            return obj.worker_id.worker_id. name
        return None
    
    def get_location(self, obj):
        """List view: local fallback only (no HTTP geocoding per row)."""
        return resolve_report_location_display_list(obj)
    
    def get_after_image_url(self, obj):
        """Convert image_after ImageField to URL for frontend"""
        if obj.image_after:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image_after.url)
            return obj.image_after.url
        return None
    
    def get_feedback(self, obj):
        """Get feedback data for this report"""
        try:
            if hasattr(obj, 'feedback') and obj.feedback:
                return {
                    'rating': obj.feedback.rating,
                    'comment': obj.feedback.comment,
                    'created_at': obj.feedback.created_at.isoformat() if obj.feedback.created_at else None,
                }
        except Exception:
            pass
        return None

    def get_is_unassigned(self, obj):
        from apps.reports.status_buckets import is_citizen_unassigned_expired
        return is_citizen_unassigned_expired(obj)

    def get_high_alert(self, obj):
        from apps.reports.status_buckets import is_citizen_unassigned_expired
        if not is_citizen_unassigned_expired(obj) or not obj.submitted_at:
            return False
        return (timezone.now() - obj.submitted_at) > timedelta(hours=48)

    def get_ai_categories(self, obj):
        from apps.reports.services.ai_categories import resolve_report_ai_categories
        return resolve_report_ai_categories(obj)
    
    def get_task_number(self, obj):
        """Skipped on list API — avoids N+1 queries; detail/worker views use full serializer."""
        if self.context.get('list_view'):
            return None

        if not obj.worker_id:
            return None
        
        # ✅ Use cache key based on worker_id (get the actual worker instance ID)
        # obj.worker_id is a Worker instance, we need its primary key
        worker_pk = obj.worker_id.pk if obj.worker_id else None
        if not worker_pk:
            return None
        cache_key = f'worker_{worker_pk}'
        
        # ✅ Initialize cache for this worker if not already done
        if cache_key not in self._task_number_cache:
            from apps.reports.models import Report
            from django.db.models import F, Case, When, DateTimeField
            
            # ✅ Get all assigned reports for this worker (both accepted and admin-assigned)
            # Order: accepted_at wale pehle (by accepted_at), phir admin-assigned (by submitted_at)
            assigned_reports = Report.objects.filter(
                worker_id=obj.worker_id,
                status__in=['Assigned', 'In Progress', 'Resolved']
            ).annotate(
                # Create a sort key: accepted_at if exists, otherwise submitted_at
                sort_key=Case(
                    When(accepted_at__isnull=False, then=F('accepted_at')),
                    default=F('submitted_at'),
                    output_field=DateTimeField()
                )
            ).order_by('sort_key', 'submitted_at').values_list('report_id', flat=True)
            
            # ✅ Create a dictionary mapping report_id to task_number (1-based index)
            task_numbers = {}
            for index, report_id in enumerate(assigned_reports, start=1):
                task_numbers[report_id] = index
            
            # ✅ Store in cache
            self._task_number_cache[cache_key] = task_numbers
        
        # ✅ Get task number from cache
        task_numbers = self._task_number_cache[cache_key]
        return task_numbers.get(obj.report_id)
    
    def get_reported_by(self, obj):
        """Return creator label for worker UI (admin name vs citizen name)."""
        if getattr(obj, 'report_source', 'citizen') == 'admin':
            adm = getattr(obj, 'created_by_admin', None)
            name = (adm.name or '').strip() if adm and getattr(adm, 'name', None) else ''
            return f'Created by {name}' if name else 'Created by Admin'
        if obj.citizen_id and obj.citizen_id.account_id == 1:
            return 'Created by Admin'
        if obj.accepted_at is None and obj.status == 'Assigned' and obj.worker_id is not None:
            return 'Assigned by Admin'
        if obj.citizen_id:
            return f'Reported by {obj.citizen_id.name}'
        return 'Reported by Citizen'


class ReportCreateSerializer(serializers. ModelSerializer):
    """Serializer for creating reports (admin panel only — admin-sourced tasks, no citizen FK)."""

    citizen_id = serializers.PrimaryKeyRelatedField(
        queryset=Account.objects.all(),
        required=False,
        allow_null=True,
    )

    @staticmethod
    def _quantize_coord(value, decimal_places: int = 8):
        from decimal import Decimal, ROUND_HALF_UP

        if value is None or value == '':
            return value
        q = Decimal('1').scaleb(-decimal_places)
        return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)

    def validate_latitude(self, value):
        if value is None:
            return value
        return self._quantize_coord(value, 8)

    def validate_longitude(self, value):
        if value is None:
            return value
        return self._quantize_coord(value, 8)

    def validate_ai_confidence(self, value):
        if value is None:
            return value
        from decimal import Decimal, ROUND_HALF_UP

        d = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if d > Decimal('9.99'):
            d = Decimal('9.99')
        if d < Decimal('0'):
            d = Decimal('0')
        return d

    class Meta:
        model = Report
        fields = [
            'citizen_id',
            'waste_type',
            'latitude',
            'longitude',
            # Human-readable address shown to workers.
            # Stored as-is so worker navigation destination matches admin/citizen.
            'location_address',
            'image_before',
            'ai_result',
            'ai_confidence',
        ]

    def validate(self, attrs):
        # Ignore any placeholder citizen_id from older clients
        attrs.pop('citizen_id', None)
        return attrs
    
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['citizen_id'] = None
        validated_data['report_source'] = 'admin'
        if request and getattr(request, 'user', None) is not None:
            from apps.admins.models import Admin

            if isinstance(request.user, Admin):
                validated_data['created_by_admin'] = request.user
        validated_data.setdefault('status', 'Pending')
        validated_data.setdefault('ai_result', 'Unverified')
        return super().create(validated_data)


class ReportUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating reports"""
    
    class Meta: 
        model = Report
        fields = [
            'status',
            'worker_id',
            'waste_type',
            'image_after',
            'ai_result',
            'ai_confidence',
        ]
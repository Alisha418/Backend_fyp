from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from apps.feedback.models import Feedback
from apps.feedback.serializers import FeedbackCreateSerializer, FeedbackSerializer
from apps.reports.models import Report
from apps.workers.models import Worker, WorkerMonthlyStats
from apps.notifications.models import Notification, RecipientType
from django.utils import timezone
from datetime import datetime
import json
import logging
from django.db.models import Avg, Count, Case, When, IntegerField

logger = logging.getLogger(__name__)


class FeedbackCreateView(APIView):
    """
    Create feedback for a resolved report
    POST /api/feedback/create/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    
    def post(self, request):
        try:
            user = request.user
            
            # Check if user is a citizen
            if user.role != 'Citizen':
                return Response({
                    'success': False,
                    'message': 'Only citizens can submit feedback'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Get data from request
            report_id = request.data.get('report_id')
            rating = request.data.get('rating')
            comment = request.data.get('comment', '')
            
            # Validate required fields
            if not report_id:
                return Response({
                    'success': False,
                    'message': 'report_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            if not rating:
                return Response({
                    'success': False,
                    'message': 'rating is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            try:
                rating = int(rating)
                if rating < 1 or rating > 5:
                    return Response({
                        'success': False,
                        'message': 'rating must be between 1 and 5'
                    }, status=status.HTTP_400_BAD_REQUEST)
            except (ValueError, TypeError):
                return Response({
                    'success': False,
                    'message': 'rating must be a number between 1 and 5'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the report
            try:
                report = Report.objects.get(report_id=report_id, citizen_id=user)
            except Report.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Report not found or not assigned to you'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Check if report is resolved
            if report.status != 'Resolved':
                return Response({
                    'success': False,
                    'message': 'Can only provide feedback for resolved reports'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if feedback already exists
            if Feedback.objects.filter(report_id=report).exists():
                return Response({
                    'success': False,
                    'message': 'Feedback already submitted for this report'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get the worker
            if not report.worker_id:
                return Response({
                    'success': False,
                    'message': 'Report is not assigned to a worker'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            worker = report.worker_id
            
            # Create feedback
            feedback = Feedback.objects.create(
                report_id=report,
                citizen_id=user,
                worker_id=worker,
                rating=rating,
                comment=comment if comment else None
            )
            
            # Update worker rating
            self._update_worker_rating(worker)
            
            # Update worker monthly stats
            self._update_worker_monthly_stats(worker, report)
            
            # Create notification for worker
            self._create_feedback_notification(feedback, worker)
            
            # Serialize feedback
            serializer = FeedbackSerializer(feedback)
            
            return Response({
                'success': True,
                'message': 'Feedback submitted successfully',
                'data': serializer.data
            }, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error creating feedback: {e}")
            return Response({
                'success': False,
                'message': f'Failed to submit feedback: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _update_worker_rating(self, worker):
        """Update worker's average rating from all feedbacks"""
        from django.db.models import Avg
        from apps.feedback.models import Feedback
        
        avg_rating = Feedback.objects.filter(
            worker_id=worker
        ).aggregate(avg=Avg('rating'))['avg']
        
        if avg_rating:
            worker.avg_rating = round(avg_rating, 2)
            worker.save(update_fields=['avg_rating'])
    
    def _update_worker_monthly_stats(self, worker, report):
        """Update worker monthly stats when feedback is received"""
        # Get current month (first day)
        current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
        
        # Get or create monthly stats
        monthly_stat, created = WorkerMonthlyStats.objects.get_or_create(
            worker_id=worker,
            month=current_month,
            defaults={
                'resolved_tasks': 0,
                'avg_rating': 0.00,
                'points': 0,
                'badge': 'Bronze'
            }
        )
        
        # Update resolved_tasks (count ALL resolved reports for this worker)
        # This represents total resolved reports (lifetime or monthly based on context)
        from django.db.models import Count, Q
        from apps.reports.models import Report
        
        # Count all resolved reports for this worker
        # Note: Since Report model doesn't have resolved_at field, we count all resolved reports
        # For monthly stats, we could use feedback creation date as proxy, but user wants total resolved
        resolved_count = Report.objects.filter(
            worker_id=worker,
            status='Resolved'
        ).count()
        
        monthly_stat.resolved_tasks = resolved_count
        
        # Update avg_rating from feedbacks received this month
        from django.db.models import Avg
        from apps.feedback.models import Feedback
        
        month_start = datetime(current_month.year, current_month.month, 1).date()
        if current_month.month == 12:
            month_end = datetime(current_month.year + 1, 1, 1).date()
        else:
            month_end = datetime(current_month.year, current_month.month + 1, 1).date()
        
        avg_rating = Feedback.objects.filter(
            worker_id=worker,
            created_at__date__gte=month_start,
            created_at__date__lt=month_end
        ).aggregate(avg=Avg('rating'))['avg']
        
        if avg_rating:
            monthly_stat.avg_rating = round(avg_rating, 2)
        else:
            monthly_stat.avg_rating = 0.00
        
        # Update points (5 points per resolved report)
        monthly_stat.points = monthly_stat.resolved_tasks * 5
        
        # Update badge based on avg_rating
        if monthly_stat.avg_rating >= 4.5:
            monthly_stat.badge = 'Diamond'
        elif monthly_stat.avg_rating >= 4.0:
            monthly_stat.badge = 'Gold'
        elif monthly_stat.avg_rating >= 3.5:
            monthly_stat.badge = 'Silver'
        else:
            monthly_stat.badge = 'Bronze'
        
        monthly_stat.save()
    
    def _create_feedback_notification(self, feedback, worker):
        """Create notification for worker when feedback is received"""
        try:
            # Get task number from report
            report = feedback.report_id
            task_number = None
            if report.accepted_at and report.worker_id:
                from apps.reports.models import Report
                accepted_reports = Report.objects.filter(
                    worker_id=report.worker_id,
                    accepted_at__isnull=False,
                    status__in=['Assigned', 'In Progress', 'Resolved']
                ).order_by('accepted_at')
                
                for index, r in enumerate(accepted_reports, start=1):
                    if r.report_id == report.report_id:
                        task_number = index
                        break
            
            # Create notification title with task number if available
            if task_number:
                notification_title = f'New Feedback Received - Task #{task_number}'
                notification_body = f'You received a {feedback.rating}-star rating for Task #{task_number} (Report #{report.report_id}).'
            else:
                notification_title = f'New Feedback Received - Report #{report.report_id}'
                notification_body = f'You received a {feedback.rating}-star rating for Report #{report.report_id}.'
            
            notification_message = {
                'title': notification_title,
                'body': notification_body,
                'type': 'feedback',
                'report_id': report.report_id,
                'task_number': task_number,
                'rating': feedback.rating,
                'comment': feedback.comment if feedback.comment else None,
                'citizen_name': feedback.citizen_id.name,
            }
            
            Notification.objects.create(
                recipient_type=RecipientType.WORKER,
                recipient_id=worker.worker_id.account_id,
                message=json.dumps(notification_message),
                title=notification_title,
                is_read=False,
                report_id=report.report_id,
            )
            
            logger.info(f'✅ Feedback notification created for worker {worker.employee_code} - Task #{task_number}')
            
        except Exception as e:
            logger.error(f'❌ Error creating feedback notification: {e}')


class FeedbackListView(APIView):
    """
    List feedbacks for a worker or citizen
    GET /api/feedback/?worker_id=<id> or ?citizen_id=<id>
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    
    def get(self, request):
        try:
            user = request.user
            queryset = Feedback.objects.all()
            
            # Filter by worker_id if provided
            worker_id = request.query_params.get('worker_id')
            if worker_id:
                try:
                    worker = Worker.objects.get(worker_id__account_id=worker_id)
                    queryset = queryset.filter(worker_id=worker)
                except Worker.DoesNotExist:
                    return Response({
                        'success': False,
                        'message': 'Worker not found'
                    }, status=status.HTTP_404_NOT_FOUND)
            
            # Filter by citizen_id if provided
            citizen_id = request.query_params.get('citizen_id')
            if citizen_id:
                queryset = queryset.filter(citizen_id__account_id=citizen_id)
            
            # Filter by report_id if provided
            report_id = request.query_params.get('report_id')
            if report_id:
                queryset = queryset.filter(report_id__report_id=report_id)
            
            serializer = FeedbackSerializer(queryset, many=True)
            
            return Response({
                'success': True,
                'count': queryset.count(),
                'data': serializer.data
            })
            
        except Exception as e:
            logger.error(f"Error listing feedbacks: {e}")
            return Response({
                'success': False,
                'message': f'Failed to fetch feedbacks: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkerFeedbackDashboardView(APIView):
    """
    Worker feedback dashboard for profile > view feedback page.
    GET /api/feedback/worker/my/
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        try:
            user = request.user

            if user.role != 'Worker':
                return Response({
                    'success': False,
                    'message': 'Only workers can access this endpoint'
                }, status=status.HTTP_403_FORBIDDEN)

            try:
                worker = Worker.objects.get(worker_id=user)
            except Worker.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Worker profile not found'
                }, status=status.HTTP_404_NOT_FOUND)

            queryset = (
                Feedback.objects
                .filter(worker_id=worker)
                .select_related('citizen_id', 'report_id', 'worker_id__worker_id')
                .order_by('-created_at')
            )

            stats = queryset.aggregate(
                overall_rating=Avg('rating'),
                total_feedbacks=Count('feedback_id'),
                positive_feedbacks=Count(
                    Case(
                        When(rating__gt=3, then=1),
                        output_field=IntegerField(),
                    )
                ),
            )
            total_feedbacks = int(stats.get('total_feedbacks') or 0)
            positive_feedbacks = int(stats.get('positive_feedbacks') or 0)
            negative_feedbacks = max(0, total_feedbacks - positive_feedbacks)
            overall_rating = round(float(stats.get('overall_rating') or 0.0), 2)

            serializer = FeedbackSerializer(queryset, many=True)

            return Response({
                'success': True,
                'data': {
                    'overall_rating': overall_rating,
                    'total_feedbacks': total_feedbacks,
                    'positive_feedbacks': positive_feedbacks,
                    'negative_feedbacks': negative_feedbacks,
                    'feedbacks': serializer.data,
                }
            }, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error fetching worker feedback dashboard: {e}")
            return Response({
                'success': False,
                'message': f'Failed to fetch worker feedback dashboard: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db. models import Count, Sum, Avg, Q
from django.utils import timezone
from datetime import datetime, timedelta, time
from rest_framework.permissions import IsAuthenticated
from apps.accounts.models import Account
from apps.workers.models import Worker
from apps.reports.models import Report
from apps.reports.status_buckets import (
    awaiting_accept_q,
    pending_workload_q,
    unassigned_expired_q,
)
from .models import UserMonthlyStats, WorkerMonthlyStats

from apps.admins.permissions import IsAdmin
from apps.admins.authentication import AdminJWTAuthentication
class DashboardStatsView(APIView):
    """
    GET /api/dashboard/stats/
    Get overall dashboard statistics
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]
    def get(self, request):
        try:
            # Reports stats
            total_reports = Report.objects.count()
            # Unassigned / awaiting = citizen pipeline only (admin tasks are not citizen reports)
            unassigned_reports = Report.objects.filter(unassigned_expired_q()).count()
            awaiting_accept_reports = Report.objects.filter(awaiting_accept_q()).count()
            # Pending = worker accepted or admin-assigned, work not started
            pending_reports = Report.objects.filter(pending_workload_q()).count()
            assigned_reports = Report.objects.filter(status='Assigned').count()
            in_progress_reports = Report.objects.filter(status='In Progress').count()
            resolved_reports = Report.objects.filter(status='Resolved').count()
            
            # Workers stats
            total_workers = Worker.objects.count()
            active_workers = Worker.objects.filter(worker_id__is_active=True).count()
            tracking_workers = Worker.objects.filter(is_tracking=True).count()
            
            # Citizens stats
            total_citizens = Account.objects.filter(role='Citizen').count()
            active_citizens = Account.objects.filter(role='Citizen', is_active=True).count()
            
            return Response({
                'success': True,
                'data':  {
                    'reports':  {
                        'total':  total_reports,
                        'unassigned': unassigned_reports,
                        'awaiting_accept': awaiting_accept_reports,
                        'pending': pending_reports,
                        'assigned': assigned_reports,
                        'in_progress':  in_progress_reports,
                        'resolved': resolved_reports
                    },
                    'workers': {
                        'total':  total_workers,
                        'active': active_workers,
                        'tracking': tracking_workers
                    },
                    'citizens': {
                        'total':  total_citizens,
                        'active': active_citizens
                    }
                }
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TopCitizensView(APIView):
    """
    GET /api/dashboard/top-citizens/
    Same ranking logic as mobile GET /api/accounts/leaderboard/:
    all active citizens (including 0 reports); ordered by report count (desc).
    Badges only for ranks 1–3 among citizens with at least one report.
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]

    def get(self, request):
        try:
            limit_param = request.query_params.get('limit', '10')
            limit = int(limit_param) if str(limit_param).isdigit() else 10

            citizens_qs = (
                Account.objects.filter(role='Citizen', is_active=True)
                .annotate(
                    verified_reports_count=Count(
                        'submitted_reports',
                        filter=Q(submitted_reports__report_source='citizen'),
                    ),
                )
                .order_by('-verified_reports_count', 'name')
            )
            citizens_list = list(citizens_qs)

            eligible = [c for c in citizens_list if (c.verified_reports_count or 0) > 0]
            ineligible = [c for c in citizens_list if (c.verified_reports_count or 0) <= 0]

            data = []

            def _append_citizen(citizen, rank, badge):
                profile_image_url = None
                if citizen.profile_image:
                    from apps.accounts.media_url import build_media_file_url

                    profile_image_url = build_media_file_url(citizen.profile_image, request)
                report_count = citizen.verified_reports_count or 0
                data.append({
                    'id': str(citizen.account_id),
                    'citizen_id': citizen.account_id,
                    'account_id': citizen.account_id,
                    'name': citizen.name or 'Unknown',
                    'email': citizen.email,
                    'verified_reports': report_count,
                    'total_reports': report_count,
                    'reports': report_count,
                    'rank': rank,
                    'badge': badge,
                    'profile_image': profile_image_url,
                    'avatar_url': profile_image_url,
                    'created_at': citizen.created_at.isoformat() if citizen.created_at else None,
                })

            for index, citizen in enumerate(eligible, start=1):
                badge = None
                if index == 1:
                    badge = 'platinum'
                elif index == 2:
                    badge = 'gold'
                elif index == 3:
                    badge = 'silver'
                _append_citizen(citizen, index, badge)

            for citizen in ineligible:
                _append_citizen(citizen, None, None)

            if limit > 0:
                data = data[:limit]

            return Response({
                'success': True,
                'count': len(data),
                'data': data,
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TopWorkersView(APIView):
    """
    GET /api/dashboard/top-workers/
    Same ranking logic as mobile GET /api/workers/rankings/:
    resolved_tasks (desc), then avg_rating, then points; rank/badge from snapshot.
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]

    def get(self, request):
        try:
            from apps.workers.badge_history_service import calculate_rankings_snapshot

            limit_param = request.query_params.get('limit', '10')
            limit = int(limit_param) if str(limit_param).isdigit() else 10

            rankings = calculate_rankings_snapshot(request=request)
            if limit > 0:
                rankings = rankings[:limit]

            data = []
            for entry in rankings:
                resolved = int(entry.get('resolved_tasks') or 0)
                avg_rating = float(entry.get('avg_rating') or 0.0)
                worker_id = entry.get('worker_id')
                active_tasks = 0
                is_tracking = False
                email = ''
                if worker_id is not None:
                    try:
                        worker = Worker.objects.select_related('worker_id').get(
                            worker_id_id=worker_id,
                        )
                        active_tasks = Report.objects.filter(
                            worker_id=worker,
                            status__in=['Assigned', 'In Progress'],
                        ).count()
                        is_tracking = worker.is_tracking
                        email = worker.worker_id.email or ''
                    except Worker.DoesNotExist:
                        pass

                data.append({
                    'id': str(worker_id),
                    'worker_id': worker_id,
                    'employee_code': entry.get('employee_code'),
                    'name': entry.get('name') or 'Unknown',
                    'email': email,
                    'resolved_tasks': resolved,
                    'tasks_completed': resolved,
                    'total_tasks': resolved,
                    'avg_rating': avg_rating,
                    'rating': avg_rating,
                    'points': entry.get('points') or 0,
                    'rank': entry.get('rank'),
                    'badge': entry.get('badge'),
                    'active_tasks': active_tasks,
                    'is_tracking': is_tracking,
                    'profile_image': entry.get('profile_image'),
                })

            return Response({
                'success': True,
                'count': len(data),
                'data': data,
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _reports_in_progress_on_date(day):
    """Reports that were in progress at some point on calendar day `day`."""
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(datetime.combine(day, time.min), tz)
    day_end = timezone.make_aware(datetime.combine(day, time.max), tz)

    return (
        Report.objects.filter(
            worker_id__isnull=False,
            started_at__isnull=False,
            started_at__lte=day_end,
        )
        .filter(Q(resolved_at__isnull=True) | Q(resolved_at__gte=day_start))
        .select_related('worker_id__worker_id')
    )


def _day_label(day, today):
    if day == today:
        return 'Today'
    if day == today - timedelta(days=1):
        return 'Yesterday'
    return day.strftime('%b %d, %Y')


class RecentActivitiesView(APIView):
    """
    GET /api/dashboard/activities/
    Per-day summary of workers with in-progress tasks (based on started_at / resolved_at).
    Query: days (default 7), limit (max day-groups returned, default 7).
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]

    def get(self, request):
        try:
            days = int(request.query_params.get('days', 7))
            limit = int(request.query_params.get('limit', 7))
            days = max(1, min(days, 31))
            limit = max(1, min(limit, 31))

            today = timezone.localdate()
            tz = timezone.get_current_timezone()
            data = []

            for offset in range(days):
                day = today - timedelta(days=offset)
                reports_qs = _reports_in_progress_on_date(day)

                worker_map = {}
                for report in reports_qs:
                    worker = report.worker_id
                    if not worker:
                        continue
                    account = worker.worker_id
                    wid = worker.pk
                    if wid not in worker_map:
                        worker_map[wid] = {
                            'worker_id': wid,
                            'worker_name': (account.name if account else None) or worker.employee_code,
                            'task_count': 0,
                        }
                    worker_map[wid]['task_count'] += 1

                if not worker_map:
                    continue

                workers = sorted(
                    worker_map.values(),
                    key=lambda w: (-w['task_count'], w['worker_name'].lower()),
                )
                names = ', '.join(
                    f"{w['worker_name']} ({w['task_count']})" for w in workers
                )
                day_label = _day_label(day, today)
                data.append({
                    'id': f'in-progress-{day.isoformat()}',
                    'type': 'in_progress',
                    'date': day.isoformat(),
                    'date_label': day_label,
                    'message': f"In progress — {names}",
                    'workers': workers,
                    'timestamp': timezone.make_aware(
                        datetime.combine(day, time.max),
                        tz,
                    ).isoformat(),
                })

                if len(data) >= limit:
                    break

            return Response({
                'success': True,
                'count': len(data),
                'data': data,
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TrendDataView(APIView):
    """
    GET /api/dashboard/trends/
    Get trend data for charts
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]
    def get(self, request):
        try:
            days = int(request.query_params.get('days', 7))
            
            data = []
            for i in range(days):
                date = timezone.now().date() - timedelta(days=days - i - 1)
                
                # Count reports submitted on this day
                reports_count = Report.objects.filter(
                    submitted_at__date=date
                ).count()
                
                # Count reports resolved on this day (use __date lookup to avoid naive datetime warning)
                resolved_count = Report.objects.filter(
                    resolved_at__date=date  # ✅ Use __date lookup instead of direct date comparison
                ).count()
                
                data.append({
                    'date': date.strftime('%b %d'),
                    'reports':  reports_count,
                    'resolved': resolved_count
                })
            
            return Response({
                'success': True,
                'data': data
            })
            
        except Exception as e: 
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StatusDistributionView(APIView):
    """
    GET /api/dashboard/status-distribution/
    Get report status distribution
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]
    def get(self, request):
        try:
            distribution = Report.objects.values('status').annotate(
                count=Count('report_id')
            )
            
            counts_by_status = {item['status']: item['count'] for item in distribution}

            awaiting_count = Report.objects.filter(awaiting_accept_q()).count()
            unassigned_count = Report.objects.filter(unassigned_expired_q()).count()
            pending_workload = Report.objects.filter(pending_workload_q()).count()

            data = []
            if awaiting_count > 0:
                data.append({
                    'name': 'Awaiting Acceptance',
                    'value': awaiting_count,
                    'color': '#64748b',
                })
            if unassigned_count > 0:
                data.append({
                    'name': 'Unassigned',
                    'value': unassigned_count,
                    'color': '#f59e0b',
                })
            if pending_workload > 0:
                data.append({
                    'name': 'Pending',
                    'value': pending_workload,
                    'color': '#ef4444',
                })
            for status in ('In Progress', 'Resolved', 'Rejected'):
                count = counts_by_status.get(status, 0)
                if count > 0:
                    status_colors = {
                        'In Progress': '#3b82f6',
                        'Resolved': '#10b981',
                        'Rejected': '#dc2626',
                    }
                    data.append({
                        'name': status,
                        'value': count,
                        'color': status_colors[status],
                    })
            
            return Response({
                'success': True,
                'data': data
            })
            
        except Exception as e: 
            return Response({
                'success': False,
                'error':  str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ZoneStatsView(APIView):
    """
    GET /api/dashboard/zone-stats/
    Aggregated report totals per reporting area (locality/address — not N/S/E/W zones).
    Query: days (default 30) — only reports with submitted_at within that window.
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]

    def get(self, request):
        try:
            from collections import defaultdict

            from apps.analytics.area_utils import reporting_area_for_report

            days_param = request.query_params.get('days', '0')
            days = int(days_param) if str(days_param).isdigit() else 0
            days = max(0, min(days, 3650))
            since = timezone.now() - timedelta(days=days) if days > 0 else None

            def _empty_bucket():
                return {
                    'pending': 0,
                    'assigned': 0,
                    'in_progress': 0,
                    'resolved': 0,
                    'rejected': 0,
                    'total': 0,
                }

            area_stats = defaultdict(_empty_bucket)

            reports_qs = Report.objects.all()
            if since is not None:
                reports_qs = reports_qs.filter(submitted_at__gte=since)

            for report in reports_qs.only(
                'report_id',
                'latitude',
                'longitude',
                'location_address',
                'status',
                'submitted_at',
            ).iterator():
                area = reporting_area_for_report(
                    location_address=report.location_address,
                    latitude=report.latitude,
                    longitude=report.longitude,
                )
                bucket = area_stats[area]
                bucket['total'] += 1
                status = report.status or ''
                if status == 'Pending':
                    bucket['pending'] += 1
                elif status == 'Assigned':
                    bucket['assigned'] += 1
                elif status == 'In Progress':
                    bucket['in_progress'] += 1
                elif status == 'Resolved':
                    bucket['resolved'] += 1
                elif status == 'Rejected':
                    bucket['rejected'] += 1

            sorted_items = sorted(
                area_stats.items(),
                key=lambda item: (-item[1]['total'], item[0]),
            )
            max_total = max((b['total'] for _, b in sorted_items), default=0)

            from apps.analytics.area_utils import severity_for_count

            data = [
                {
                    'area': area,
                    'total_reports': bucket['total'],
                    'reports': bucket['total'],
                    'pending': bucket['pending'],
                    'assigned': bucket['assigned'],
                    'in_progress': bucket['in_progress'],
                    'resolved': bucket['resolved'],
                    'rejected': bucket['rejected'],
                    'severity': severity_for_count(bucket['total'], max_total),
                }
                for area, bucket in sorted_items
            ]

            return Response({
                'success': True,
                'count': len(data),
                'period_days': days if days > 0 else None,
                'data': data,
            })

        except Exception as e:
            return Response({
                'success': False,
                'error': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
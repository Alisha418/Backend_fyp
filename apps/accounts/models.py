from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
import uuid


class AccountManager(BaseUserManager):
    """Custom manager for Account model"""
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user"""
        if not email: 
            raise ValueError('Email is required')
        
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        
        if password:
            user.set_password(password)
        
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser"""
        extra_fields.setdefault('role', 'Citizen')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        
        return self.create_user(email, password, **extra_fields)


class Account(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model for citizens and workers
    Uses email as the unique identifier instead of username
    """
    
    ROLE_CHOICES = (
        ('Citizen', 'Citizen'),
        ('Worker', 'Worker'),
    )
    
    # Primary Key
    account_id = models.AutoField(primary_key=True)
    # ✅ ADD: Property to make it compatible with Django's default 'id'
    @property
    def id(self):
        """Alias for account_id to maintain compatibility"""
        return self.account_id
    
    # ✅ ADD: pk property (Django expects this)
    @property
    def pk(self):
        """Primary key alias"""
        return self.account_id
    @property
    def pk(self):
        """Alias for primary key"""
        return self.account_id
    
    
    def __str__(self):
        return f"{self.name} ({self.email})"
    # Authentication
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    password_hash = models.CharField(max_length=255)
    
    # Profile Information
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='Citizen')
    name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    
    # Image Field
    profile_image = models. ImageField(
        upload_to='profiles/',
        null=True,
        blank=True,
        max_length=512
    )
    
    # OAuth
    google_id = models.CharField(max_length=255, null=True, blank=True, unique=True)

    # Firebase Cloud Messaging (mobile push)
    fcm_token = models.TextField(null=True, blank=True)
    fcm_token_updated_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)
    
    # ✅ NEW: Session Management Fields
    last_activity = models.DateTimeField(null=True, blank=True)
    login_count = models.IntegerField(default=0)
    failed_login_attempts = models.IntegerField(default=0)
    last_failed_login = models.DateTimeField(null=True, blank=True)
    account_locked_until = models.DateTimeField(null=True, blank=True)
    
    # Permissions
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    objects = AccountManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    
    # Override default password field
    password = None
    
    class Meta:
        db_table = 'accounts'
        verbose_name = 'Account'
        verbose_name_plural = 'Accounts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['role']),
            models.Index(fields=['google_id']),
            models.Index(fields=['last_activity']),  # NEW
        ]
    
    def __str__(self):
        return f"{self.name} ({self.email})"
    
    def set_password(self, raw_password):
        """Hash and set password"""
        self.password_hash = make_password(raw_password)
    
    def check_password(self, raw_password):
        """Verify password"""
        return check_password(raw_password, self. password_hash)
    
    def get_full_name(self):
        """Return the user's full name"""
        return self.name
    
    def get_short_name(self):
        """Return the user's short name"""
        return self.name. split()[0] if self.name else self.email
    
    def get_profile_image_url(self):
        """Return full URL for profile image"""
        if self.profile_image:
            return self.profile_image.url
        return None
    
    # ✅ NEW: Session Management Methods
    def is_account_locked(self):
        """Check if account is locked due to failed login attempts"""
        if self.account_locked_until: 
            if timezone.now() < self.account_locked_until:
                return True
            else:
                # Lock period expired, reset
                self.account_locked_until = None
                self.failed_login_attempts = 0
                self.save(update_fields=['account_locked_until', 'failed_login_attempts'])
        return False
    
    def increment_failed_login(self):
        """Increment failed login attempts and lock if needed"""
        self.failed_login_attempts += 1
        self.last_failed_login = timezone.now()
        
        # Lock account after 5 failed attempts for 15 minutes
        if self.failed_login_attempts >= 5:
            self.account_locked_until = timezone.now() + timezone.timedelta(minutes=15)
        
        self.save(update_fields=['failed_login_attempts', 'last_failed_login', 'account_locked_until'])
    
    def reset_failed_login(self):
        """Reset failed login attempts"""
        self.failed_login_attempts = 0
        self.last_failed_login = None
        self.account_locked_until = None
        self.save(update_fields=['failed_login_attempts', 'last_failed_login', 'account_locked_until'])
    
    def update_last_login(self):
        """Update last login timestamp"""
        self.last_login = timezone.now()
        self.last_activity = timezone.now()
        self.login_count += 1
        self.save(update_fields=['last_login', 'last_activity', 'login_count'])
    
    def update_last_activity(self):
        """Update last activity timestamp"""
        self.last_activity = timezone.now()
        self.save(update_fields=['last_activity'])


# ✅ NEW: Session Model
class UserSession(models.Model):
    """
    Track active user sessions
    """
    DEVICE_TYPE_CHOICES = (
        ('mobile', 'Mobile'),
        ('tablet', 'Tablet'),
        ('desktop', 'Desktop'),
        ('unknown', 'Unknown'),
    )
    
    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='sessions')
    
    # Session Details
    refresh_token = models.CharField(max_length=512, unique=True)
    access_token = models.CharField(max_length=512)
    
    # Device Information
    device_type = models.CharField(max_length=20, choices=DEVICE_TYPE_CHOICES, default='unknown')
    device_name = models.CharField(max_length=255, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    # Geolocation
    location = models.CharField(max_length=255, null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    last_activity = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    
    # Status
    is_active = models.BooleanField(default=True)
    logged_out_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'user_sessions'
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['account', 'is_active']),
            models. Index(fields=['refresh_token']),
            models.Index(fields=['expires_at']),
        ]
    
    def __str__(self):
        return f"{self.account.email} - {self.device_type} - {self.created_at}"
    
    def is_expired(self):
        """Check if session is expired"""
        return timezone.now() > self.expires_at
    
    def extend_session(self):
        """Extend session expiry"""
        self.last_activity = timezone.now()
        self.expires_at = timezone.now() + timezone.timedelta(days=7)
        self.save(update_fields=['last_activity', 'expires_at'])
    
    def terminate(self):
        """Terminate session"""
        self.is_active = False
        self.logged_out_at = timezone.now()
        self.save(update_fields=['is_active', 'logged_out_at'])


# ✅ NEW: Login History Model
class LoginHistory(models. Model):
    """
    Track login history for security auditing
    """
    LOGIN_STATUS_CHOICES = (
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('blocked', 'Blocked'),
    )
    
    history_id = models.AutoField(primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='login_history')
    
    # Login Details
    status = models.CharField(max_length=50, choices=LOGIN_STATUS_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    device_type = models.CharField(max_length=50, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    
    # Failure Reason
    failure_reason = models. CharField(max_length=255, null=True, blank=True)
    
    # Timestamp
    attempted_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'login_history'
        ordering = ['-attempted_at']
        indexes = [
            models.Index(fields=['account', '-attempted_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.account.email} - {self.status} - {self.attempted_at}"
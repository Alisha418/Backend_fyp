from rest_framework import serializers
from .models import Admin
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class AdminSerializer(serializers.ModelSerializer):
    """Serializer for Admin model"""

    class Meta:
        model = Admin
        fields = [
            'admin_id', 'email', 'name', 'role',
            'created_at', 'last_login', 'is_active'
        ]
        read_only_fields = ['admin_id', 'created_at', 'last_login']


class AdminCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating new admin"""
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = Admin
        fields = [
            'email', 'name', 'password', 'password_confirm', 'role'
        ]

    def validate(self, attrs):
        """Validate password match"""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password": "Password fields didn't match."
            })

        # Validate password strength
        try:
            validate_password(attrs['password'])
        except ValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})

        return attrs

    def create(self, validated_data):
        """Create admin with hashed password"""
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')

        admin = Admin.objects.create(**validated_data)
        admin.set_password(password)
        admin.save()

        return admin


class AdminUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating admin"""

    class Meta:
        model = Admin
        fields = ['name', 'role', 'is_active']


class AdminLoginSerializer(serializers.Serializer):
    """Serializer for admin login"""
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )


class AdminPasswordChangeSerializer(serializers.Serializer):
    """Serializer for password change"""
    old_password = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )
    new_password = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )
    new_password_confirm = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                "new_password": "Password fields didn't match."
            })

        try:
            validate_password(attrs['new_password'])
        except ValidationError as e:
            raise serializers.ValidationError({"new_password": list(e.messages)})

        return attrs


class PasswordResetRequestSerializer(serializers.Serializer):
    """Serializer for password reset request"""
    email = serializers.EmailField(required=True)


class PasswordResetConfirmSerializer(serializers.Serializer):
    """Serializer for password reset confirmation"""
    token = serializers.CharField(required=True)
    new_password = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )
    new_password_confirm = serializers.CharField(
        required=True,
        style={'input_type': 'password'}
    )

    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError({
                "new_password": "Password fields didn't match."
            })

        try:
            validate_password(attrs['new_password'])
        except ValidationError as e:
            raise serializers.ValidationError({"new_password": list(e.messages)})

        return attrs

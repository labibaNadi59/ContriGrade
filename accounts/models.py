from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email, name, role, password=None):
        if not email:
            raise ValueError("An institutional email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, name=name, role=role)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, password=None):
        # Changed this to use the new ADMIN role
        user = self.create_user(
            email=email,
            name=name,
            role=User.Role.ADMIN,
            password=password,
        )
        user.is_staff = True
        user.is_superuser = True
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'  # Added Admin role here
        STUDENT = 'STUDENT', 'Student'
        INSTRUCTOR = 'INSTRUCTOR', 'Instructor'
        COORDINATOR = 'COORDINATOR', 'Course Coordinator'

    user_id = models.AutoField(primary_key=True)
    email = models.EmailField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_instructor(self):
        return self.role == self.Role.INSTRUCTOR

    @property
    def is_coordinator(self):
        return self.role == self.Role.COORDINATOR

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN
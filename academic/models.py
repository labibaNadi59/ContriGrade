from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Course(models.Model):
    course_id = models.AutoField(primary_key=True)
    course_name = models.CharField(max_length=255)
    course_code = models.CharField(max_length=50, unique=True)
    coordinator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        related_name='coordinated_courses',
        limit_choices_to={'role': 'COORDINATOR'}
    )

    def __str__(self):
        return f"{self.course_code} - {self.course_name}"


class CourseSection(models.Model):
    section_id = models.AutoField(primary_key=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='sections')
    section_name = models.CharField(max_length=50, help_text="e.g. Section A, Section B")
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        related_name='assigned_sections',
        limit_choices_to={'role': 'INSTRUCTOR'},
        null=True,
        blank=True
    )

    class Meta:
        unique_together = ('course', 'section_name')

    def __str__(self):
        return f"{self.course.course_code} - {self.section_name}"


class Project(models.Model):
    project_id = models.AutoField(primary_key=True)
    section = models.ForeignKey(CourseSection, on_delete=models.CASCADE, related_name='projects')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    deadline = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        # Prevent creating projects with deadlines in the past (Task T3.3)
        if self.deadline and self.deadline <= timezone.now():
            raise ValidationError({'deadline': "Project deadline cannot be set in the past."})

    def is_active(self):
        return timezone.now() <= self.deadline

    def __str__(self):
        return f"{self.title} ({self.section})"


class Team(models.Model):
    team_id = models.AutoField(primary_key=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='teams')
    team_name = models.CharField(max_length=255)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through='TeamMember',
        related_name='student_teams'
    )

    class Meta:
        unique_together = ('project', 'team_name')

    def __str__(self):
        return f"{self.team_name} - {self.project.title}"


class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'STUDENT'}
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('team', 'user')

    def clean(self):
        # Task T4.2 rule: A student can belong to only ONE team per project
        existing_membership = TeamMember.objects.filter(
            team__project=self.team.project,
            user=self.user
        ).exclude(pk=self.pk)

        if existing_membership.exists():
            raise ValidationError(
                f"{self.user.name} is already assigned to a team in this project."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.name} -> {self.team.team_name}"
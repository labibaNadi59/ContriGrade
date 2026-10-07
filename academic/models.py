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
    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='sections')
    section_name = models.CharField(max_length=50, help_text="e.g. Section A, Section B")
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.RESTRICT,
        related_name='assigned_sections',
        limit_choices_to={'role': 'INSTRUCTOR'},
        null=True,
        blank=True
    )
    #Link students directly to the section
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        limit_choices_to={'role': 'STUDENT'},
        related_name='enrolled_sections',
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
    github_repo_url = models.URLField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Format: https://github.com/username/repository"
    )

    class Meta:
        unique_together = ('project', 'team_name')

    def __str__(self):
        return f"{self.team_name} - {self.project.title}"


class TeamMember(models.Model):
    team = models.ForeignKey('Team', on_delete=models.CASCADE)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        limit_choices_to={'role': 'STUDENT'}
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    role_in_team = models.CharField(max_length=120, blank=True, default='', verbose_name="Individual Project Role")
    responsibilities = models.TextField(blank=True, default='', verbose_name="Documented Responsibilities")

    class Meta:
        unique_together = ('team', 'user')

    def clean(self):
        # One team per project
        existing_membership = TeamMember.objects.filter(
            team__project=self.team.project,
            user=self.user
        ).exclude(pk=self.pk)

        if existing_membership.exists():
            raise ValidationError(f"{self.user.name} is already assigned to a team in this project.")

        # Student MUST be enrolled in the section to join a team
        if not self.team.project.section.students.filter(pk=self.user.pk).exists():
            raise ValidationError(
                f"Security block: {self.user.name} cannot be assigned to this team because they are not enrolled in {self.team.project.section}."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.name} -> {self.team.team_name}"



class NonCodingDeliverable(models.Model):
    deliverable_id = models.AutoField(primary_key=True)
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='deliverables')
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=255, help_text="e.g., Figma Design, SRS Document")
    link = models.URLField(max_length=500, help_text="Must be a valid URL starting with http:// or https://")
    description = models.TextField(blank=True, default='')
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.team.team_name})"


class DeliverableContribution(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Verification'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
    )

    deliverable = models.ForeignKey(NonCodingDeliverable, on_delete=models.CASCADE, related_name='contributions')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    contribution_area = models.CharField(max_length=255,
                                         help_text="e.g., Designed the database ERD, Wrote the abstract")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student.name} - {self.contribution_area} ({self.get_status_display()})"


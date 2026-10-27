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


class CourseAssessmentPolicy(models.Model):
    course = models.OneToOneField(Course, on_delete=models.CASCADE, related_name='assessment_policy')
    weight_github = models.PositiveIntegerField(default=40, help_text="Standard weight for GitHub Analytics (%)")
    weight_deliverables = models.PositiveIntegerField(default=30, help_text="Standard weight for Deliverables (%)")
    weight_peer = models.PositiveIntegerField(default=30, help_text="Standard weight for Peer Evaluation (%)")
    last_updated = models.DateTimeField(auto_now=True)

    def clean(self):
        total = (self.weight_github or 0) + (self.weight_deliverables or 0) + (self.weight_peer or 0)
        if total != 100:
            raise ValidationError(f"Course policy weights must sum to exactly 100%. Current total is {total}%.")

    def __str__(self):
        return f"Policy for {self.course.course_code}"


class PolicyChangeRequest(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )
    request_id = models.AutoField(primary_key=True)
    project = models.ForeignKey('Project', on_delete=models.CASCADE, related_name='policy_requests')
    instructor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    proposed_github = models.PositiveIntegerField()
    proposed_deliverables = models.PositiveIntegerField()
    proposed_peer = models.PositiveIntegerField()

    justification = models.TextField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='PENDING')

    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        total = (self.proposed_github or 0) + (self.proposed_deliverables or 0) + (self.proposed_peer or 0)
        if total != 100:
            raise ValidationError("Proposed weights must sum exactly to 100%.")


class CourseSection(models.Model):
    section_id = models.AutoField(primary_key=True)
    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='sections')
    section_name = models.CharField(max_length=50, help_text="e.g. Section A, Section B")
    enrollment_code = models.CharField(max_length=12, unique=True, null=True, blank=True)
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

    # Assessment Weight Fields (Defaulting to a balanced 100%)
    weight_github = models.PositiveIntegerField(default=40, help_text="Weight for GitHub Analytics (%)")
    weight_deliverables = models.PositiveIntegerField(default=30, help_text="Weight for Deliverables (%)")
    weight_peer = models.PositiveIntegerField(default=30, help_text="Weight for Peer Evaluation (%)")

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        # Prevent creating projects with deadlines in the past
        if self.deadline and self.deadline <= timezone.now():
            raise ValidationError({'deadline': "Project deadline cannot be set in the past."})

        #Only enforce the 100% rule if the project already exists (editing).
        # When creating a new project, the dashboard view securely forces the weights.
        if self.pk:
            total_weight = (self.weight_github or 0) + (self.weight_deliverables or 0) + (self.weight_peer or 0)
            if total_weight != 100:
                raise ValidationError(
                    f"Assessment weights must sum to exactly 100%. Your current total is {total_weight}%.")
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


class EvaluationCriterion(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='evaluation_criteria')
    name = models.CharField(max_length=100, help_text="e.g., Technical Contribution, Communication, Punctuality")
    description = models.TextField(blank=True, help_text="Optional breakdown of what this criterion means")
    max_score = models.IntegerField(default=5, help_text="Maximum possible score (default is 5)")

    def __str__(self):
        return f"{self.name} - {self.project.title}"


class PeerEvaluation(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='evaluations')
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='evaluations_given'
    )
    evaluatee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='evaluations_received'
    )
    general_feedback = models.TextField(blank=True, help_text="Anonymous text feedback for the teammate")
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # A student can only evaluate a specific teammate once per team
        unique_together = ('team', 'evaluator', 'evaluatee')

    def __str__(self):
        return f"Evaluation in {self.team.team_name} (To: {self.evaluatee.name})"


class PeerEvaluationScore(models.Model):
    evaluation = models.ForeignKey(PeerEvaluation, on_delete=models.CASCADE, related_name='scores')
    criterion = models.ForeignKey(EvaluationCriterion, on_delete=models.CASCADE)
    score = models.IntegerField()

    class Meta:
        # A specific evaluation can only have one score per criterion
        unique_together = ('evaluation', 'criterion')

    def __str__(self):
        return f"{self.criterion.name}: {self.score}"


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    # Optional: A link so they can click the notification and go directly to the project
    link = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Notification for {self.recipient.name}: {self.message}"


class FinalAssessment(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='final_assessments')
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='final_assessments')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='final_assessments')

    recommended_score = models.FloatField(default=0.0, help_text="System-calculated contribution score snapshot")
    adjusted_score = models.FloatField(null=True, blank=True, help_text="Instructor-adjusted final score (0-100)")
    viva_observations = models.TextField(blank=True, help_text="Observations recorded during viva/defense")
    adjustment_reason = models.CharField(max_length=255, blank=True,
                                         help_text="Reason for adjusting the recommended score")

    # NEW: Final Score Approval Tracking
    is_approved = models.BooleanField(default=False, help_text="Whether the final score has been officially approved")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_assessments'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='graded_assessments'
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('project', 'student')

    @property
    def effective_final_score(self):
        return self.adjusted_score if self.adjusted_score is not None else self.recommended_score

    def __str__(self):
        status = "Approved" if self.is_approved else "Draft"
        return f"{self.student.name} - {self.project.title} ({self.effective_final_score}% - {status})"


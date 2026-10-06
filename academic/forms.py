from django import forms
from django.contrib.auth import get_user_model

from .models import Project, Team, Course, TeamMember, NonCodingDeliverable
from accounts.models import User
from .models import CourseSection
from .utils import validate_github_repo_url



class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['title', 'description', 'section', 'deadline']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm',
                                            'placeholder': 'e.g. E-Commerce Platform'}),
            'description': forms.Textarea(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm', 'rows': 3}),
            'section': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm bg-white'}),
            'deadline': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'w-full px-3 py-2 border rounded-lg text-sm'}),
        }

    def __init__(self, *args, **kwargs):
        # Pop the user passed from the view
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user:
            if user.role == 'INSTRUCTOR':
                # Restrict sections strictly to those assigned to this instructor by the coordinator
                self.fields['section'].queryset = CourseSection.objects.filter(instructor=user)
            elif user.is_coordinator:
                # Coordinators can view all sections across the board
                self.fields['section'].queryset = CourseSection.objects.all()


User = get_user_model()


class TeamForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(role='STUDENT'),  # Default fallback
        widget=forms.SelectMultiple(attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'size': '5'}),
        help_text="Hold Ctrl (or Cmd) to select multiple students. Only students enrolled in the section will appear.",
        required=False
    )

    class Meta:
        model = Team
        fields = ['project', 'team_name']
        widgets = {
            'project': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'team_name': forms.TextInput(
                attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'placeholder': 'e.g., VoltShare'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # 1. Restrict Project Choices
        if user:
            if user.role == 'INSTRUCTOR':
                self.fields['project'].queryset = Project.objects.filter(section__instructor=user)
            elif user.is_coordinator:
                self.fields['project'].queryset = Project.objects.all()

        # 2. Dynamic Student Member Filtering
        if 'project' in self.data:
            # If form was submitted (POST), lock dropdown to students of the chosen project's section
            try:
                project_id = int(self.data.get('project'))
                project = Project.objects.get(pk=project_id)
                self.fields['members'].queryset = project.section.students.all()
            except (ValueError, TypeError, Project.DoesNotExist):
                pass

        elif self.instance and self.instance.pk:
            # If editing an existing team, only show students in that project's section
            self.fields['members'].queryset = self.instance.project.section.students.all()
            self.fields['members'].initial = self.instance.members.all()

        elif user and user.role == 'INSTRUCTOR':
            # Default GET state for instructors: Only show students enrolled in *any* of their assigned sections
            self.fields['members'].queryset = User.objects.filter(enrolled_sections__instructor=user).distinct()


class CourseSectionForm(forms.ModelForm):
    class Meta:
        model = CourseSection
        fields = ['course', 'section_name', 'instructor']
        widgets = {
            'course': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm bg-white'}),
            'section_name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm', 'placeholder': 'e.g. Section C'}),
            'instructor': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm bg-white'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['instructor'].queryset = User.objects.filter(role='INSTRUCTOR')
        self.fields['instructor'].required = False


class AssignInstructorForm(forms.ModelForm):
    class Meta:
        model = CourseSection
        fields = ['instructor']
        widgets = {
            'instructor': forms.Select(attrs={'class': 'w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm bg-white'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Restrict choices strictly to users with the INSTRUCTOR role
        self.fields['instructor'].queryset = User.objects.filter(role='INSTRUCTOR')
        self.fields['instructor'].required = False
        self.fields['instructor'].label = ""
        self.fields['instructor'].empty_label = "-- Select Instructor --"  # <-- This handles empty selections safely

    def clean_instructor(self):
        instructor = self.cleaned_data.get('instructor')
        # If the user selected the empty option, ensure it returns None instead of raising an error
        return instructor if instructor else None


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['course_code', 'course_name', 'coordinator']
        widgets = {
            'course_code': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm', 'placeholder': 'e.g. CSE314'}),
            'course_name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm', 'placeholder': 'e.g. Software Engineering Lab'}),
            'coordinator': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg text-sm bg-white'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['coordinator'].queryset = User.objects.filter(role='COORDINATOR')
        self.fields['coordinator'].label = "Course Coordinator"



ROLE_CHOICES = [
    ('', '-- Select a Project Role --'),
    ('Frontend Developer', 'Frontend Developer'),
    ('Backend Developer', 'Backend Developer'),
    ('Full Stack Developer', 'Full Stack Developer'),
    ('Database Administrator', 'Database Administrator'),
    ('DevOps / Infrastructure Engineer', 'DevOps / Infrastructure Engineer'),
    ('UI/UX Designer', 'UI/UX Designer'),
    ('QA / Testing Engineer', 'QA / Testing Engineer'),
    ('Project Manager / Scrum Master', 'Project Manager / Scrum Master'),
    ('Data Engineer / Analyst', 'Data Engineer / Analyst'),
    ('Other', 'Other (Specify below)'),
]

class StudentProjectRoleForm(forms.ModelForm):
    role_choice = forms.ChoiceField(
        choices=ROLE_CHOICES,
        required=True,
        label="Designated Role",
        widget=forms.Select(attrs={
            'id': 'id_role_choice',
            'class': 'w-full px-3.5 py-2.5 bg-gray-50 border border-gray-300 rounded-lg text-sm text-gray-900 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition'
        })
    )
    custom_role = forms.CharField(
        required=False,
        label="Specify Custom Role",
        widget=forms.TextInput(attrs={
            'id': 'id_custom_role',
            'class': 'w-full px-3.5 py-2.5 bg-gray-50 border border-gray-300 rounded-lg text-sm text-gray-900 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition',
            'placeholder': 'Enter your specific role title...'
        })
    )

    class Meta:
        model = TeamMember
        fields = ['responsibilities']
        widgets = {
            'responsibilities': forms.Textarea(attrs={
                'class': 'w-full px-3.5 py-2.5 bg-gray-50 border border-gray-300 rounded-lg text-sm text-gray-900 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition',
                'rows': 4,
                'placeholder': 'Document your key deliverables and expected individual contributions...'
            }),
        }
        labels = {
            'responsibilities': 'Key Deliverables & Responsibilities',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate role_choice and custom_role if instance already has role_in_team
        if self.instance and self.instance.role_in_team:
            existing = self.instance.role_in_team
            preset_values = [choice[0] for choice in ROLE_CHOICES if choice[0] and choice[0] != 'Other']
            if existing in preset_values:
                self.fields['role_choice'].initial = existing
            else:
                self.fields['role_choice'].initial = 'Other'
                self.fields['custom_role'].initial = existing

    def clean(self):
        cleaned_data = super().clean()
        role_choice = cleaned_data.get('role_choice')
        custom_role = cleaned_data.get('custom_role', '').strip()

        if role_choice == 'Other':
            if not custom_role:
                self.add_error('custom_role', 'Please specify your custom role.')
            else:
                self.final_role = custom_role
        else:
            self.final_role = role_choice

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.role_in_team = self.final_role
        if commit:
            instance.save()
        return instance


class StudentEnrollmentForm(forms.Form):
    section = forms.ModelChoiceField(
        queryset=None,
        empty_label="-- Select a Course Section to Join --",
        widget=forms.Select(attrs={
            'class': 'flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 outline-none',
            'required': True
        })
    )

    def __init__(self, *args, **kwargs):
        # Extract the user to filter the dropdown
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        from .models import CourseSection
        qs = CourseSection.objects.select_related('course', 'instructor')

        if user:
            # Find all courses the student is already in, and exclude them from the dropdown
            enrolled_course_ids = user.enrolled_sections.values_list('course_id', flat=True)
            qs = qs.exclude(course_id__in=enrolled_course_ids)

        self.fields['section'].queryset = qs
        self.fields['section'].label_from_instance = lambda \
            obj: f"{obj.course.course_code} - {obj.section_name} (Inst: {obj.instructor.name if obj.instructor else 'TBA'})"





class TeamRepoForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['github_repo_url']
        widgets = {
            'github_repo_url': forms.URLInput(attrs={
                'class': 'w-full px-3.5 py-2.5 bg-gray-50 border border-gray-300 rounded-lg text-sm text-gray-900 focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition',
                'placeholder': 'https://github.com/username/repository'
            })
        }
        labels = {
            'github_repo_url': 'GitHub Repository URL'
        }

    def clean_github_repo_url(self):
        url = self.cleaned_data.get('github_repo_url')
        if url:
            # Run our API validation utility!
            validation = validate_github_repo_url(url)

            if not validation['valid']:
                # If GitHub says it's invalid/not found, raise a form error instantly
                raise forms.ValidationError(validation['error'])

            # Return the cleaned version of the URL (without .git at the end)
            return validation['clean_url']
        return url


class NonCodingDeliverableForm(forms.ModelForm):
    class Meta:
        model = NonCodingDeliverable
        fields = ['title', 'link', 'description']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full rounded-lg border-gray-300 focus:border-blue-500 focus:ring-blue-500', 'placeholder': 'e.g., Figma UI Wireframes'}),
            'link': forms.URLInput(attrs={'class': 'w-full rounded-lg border-gray-300 focus:border-blue-500 focus:ring-blue-500', 'placeholder': 'https://...'}),
            'description': forms.Textarea(attrs={'class': 'w-full rounded-lg border-gray-300 focus:border-blue-500 focus:ring-blue-500', 'rows': 3, 'placeholder': 'Optional notes about this deliverable...'}),
        }

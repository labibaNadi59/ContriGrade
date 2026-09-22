from django import forms
from .models import Project, Team, Course
from accounts.models import User
from .models import CourseSection



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


class TeamForm(forms.ModelForm):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(role='STUDENT'),
        widget=forms.SelectMultiple(attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'size': '5'}),
        help_text="Hold Ctrl (or Cmd) to select multiple students.",
        required=False
    )

    class Meta:
        model = Team
        fields = ['project', 'team_name']
        widgets = {
            'project': forms.Select(attrs={'class': 'w-full px-3 py-2 border rounded-lg'}),
            'team_name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 border rounded-lg', 'placeholder': 'e.g., VoltShare'}),
        }

    def __init__(self, *args, **kwargs):
        # Extract the user passed from the view for authorization filtering
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Restrict project choices based on role authorization
        if user:
            if user.role == 'INSTRUCTOR':
                self.fields['project'].queryset = Project.objects.filter(section__instructor=user)
            elif user.is_coordinator:
                self.fields['project'].queryset = Project.objects.all()

        if self.instance and self.instance.pk:
            self.fields['members'].initial = self.instance.members.all()

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
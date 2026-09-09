from django.contrib import admin
from .models import Course, CourseSection, Project, Team, TeamMember

admin.site.register(Course)
admin.site.register(CourseSection)
admin.site.register(Project)
admin.site.register(Team)
admin.site.register(TeamMember)
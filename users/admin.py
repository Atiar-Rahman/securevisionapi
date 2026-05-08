from django.contrib import admin
from users.models import User
from django.contrib.auth.admin import UserAdmin

class CustomUserAdmin(UserAdmin):
    model = User

    list_display = ('email','first_name','last_name','is_active')
    list_filter = ('is_staff','is_active')

    fieldsets =(
        (None,{'fields':('email','password')}),
        ('Personal Info',{'fields':('first_name','last_name','address','phone_number',)}),
        ('Permissions',{'fields':('is_staff','is_active','is_superuser','groups','user_permissions')}),
        ('Important Dates',{'fields':('last_login','date_joined')}),
    )
    add_fieldsets = (
        (None,{
            'classes':('wide',),
            'fields':('email','password1','password2','is_staff','is_active')
        })
    )

    search_fields = ('email','first_name','last_name')

    ordering = ('email',)



admin.site.register(User, CustomUserAdmin)
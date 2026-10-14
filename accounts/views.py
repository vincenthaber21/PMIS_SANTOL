"""Views for accounts app."""
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.cache import cache_control
from .models import Role, User
from .forms import LoginForm, UserCreateForm, UserEditForm, ProfileForm, ProfilePasswordChangeForm, RoleForm
from .emails import send_account_created_email, send_user_creation_otp_email
from .otp import store_pending_registration, resend_otp, verify_otp, mask_email, OTP_TTL_SECONDS
from core.models import AuditLog, SiteSettings
from core.logo_image import remove_logo_background, logo_to_png_bytes, login_logo_cache_key


def _serialize_user(user):
    """Serialize user for AJAX create/edit responses."""
    return {
        'pk': user.pk,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'phone': user.phone,
        'role': user.role_id or '',
        'role_name': str(user.role) if user.role else '—',
        'department': user.department_id or '',
        'department_name': str(user.department) if user.department else '—',
        'full_name': user.get_full_name() or '—',
        'is_active': user.is_active,
        'edit_url': reverse('users:user_edit', args=[user.pk]),
        'delete_url': reverse('users:user_delete', args=[user.pk]),
    }


@cache_control(public=True, max_age=86400)
def login_logo_view(request):
    """Serve the site logo with light backgrounds removed for the login page."""
    site = SiteSettings.get_solo()
    if not site.logo:
        raise Http404

    cache_key = login_logo_cache_key(site.logo.name)
    png_bytes = cache.get(cache_key)
    if png_bytes is None:
        with site.logo.open('rb') as logo_file:
            processed = remove_logo_background(logo_file)
        try:
            png_bytes = logo_to_png_bytes(processed)
        finally:
            processed.close()
        cache.set(cache_key, png_bytes, timeout=60 * 60 * 24 * 7)

    return HttpResponse(png_bytes, content_type='image/png')


def login_view(request):
    """Handle user login."""
    if request.user.is_authenticated:
        return redirect('core:dashboard')

    form = LoginForm()
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            user = authenticate(
                request,
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password']
            )
            if user:
                if not user.is_superuser and not user.can_access_site:
                    messages.error(
                        request,
                        'Your account role does not have website access. Contact an administrator.',
                    )
                else:
                    login(request, user)
                    AuditLog.objects.create(
                        user=user, action='LOGIN',
                        model_name='User', object_id=user.pk,
                        details=f'{user.username} logged in'
                    )
                    return redirect(request.GET.get('next', 'core:dashboard'))
            else:
                messages.error(request, 'Invalid username or password.')

    return render(request, 'accounts/login.html', {'form': form})


@login_required
def logout_view(request):
    """Handle user logout."""
    AuditLog.objects.create(
        user=request.user, action='LOGOUT',
        model_name='User', object_id=request.user.pk,
        details=f'{request.user.username} logged out'
    )
    logout(request)
    return redirect('accounts:login')


@login_required
def profile_view(request):
    """View/edit own profile and change password."""
    profile_form = ProfileForm(instance=request.user)
    password_form = ProfilePasswordChangeForm(user=request.user)

    if request.method == 'POST':
        if 'change_password' in request.POST:
            password_form = ProfilePasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Password changed successfully.')
                return redirect('accounts:profile')
        else:
            profile_form = ProfileForm(request.POST, request.FILES, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('accounts:profile')

    return render(request, 'accounts/profile.html', {
        'form': profile_form,
        'password_form': password_form,
    })


@login_required
def user_list(request):
    """List all users (Admin only)."""
    if not request.user.is_admin:
        messages.error(request, 'Access denied.')
        return redirect('core:dashboard')

    users = User.objects.select_related('department', 'role').order_by('username')
    search = request.GET.get('search', '')
    if search:
        users = users.filter(username__icontains=search) | \
                users.filter(first_name__icontains=search) | \
                users.filter(last_name__icontains=search)

    role_filter = request.GET.get('role', '')
    if role_filter:
        users = users.filter(role_id=role_filter)

    paginator = Paginator(users, 15)
    page = paginator.get_page(request.GET.get('page'))
    return render(request, 'accounts/user_list.html', {
        'page_obj': page, 'search': search, 'role_filter': role_filter,
        'roles': list(Role.objects.filter(status=Role.STATUS_ACTIVE).values_list('pk', 'name')),
        'create_form': UserCreateForm(),
        'edit_form': UserEditForm(),
    })


@login_required
def role_create(request):
    """Create a new role (AJAX)."""
    if not request.user.is_admin:
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    form = RoleForm(request.POST)
    if not form.is_valid():
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'errors': {field: list(errs) for field, errs in form.errors.items()},
            }, status=400)
        errors = '; '.join(
            err for field_errors in form.errors.values() for err in field_errors
        )
        return JsonResponse({'success': False, 'error': errors or 'Invalid input.'}, status=400)

    role = form.save(commit=False)
    role.apply_named_default(fallback='staff')
    role.save()
    AuditLog.objects.create(
        user=request.user, action='CREATE',
        model_name='Role', object_id=role.pk,
        details=f'Created role: {role.name}',
    )
    return JsonResponse({
        'success': True,
        'id': role.pk,
        'name': role.name,
    })


@login_required
def user_create_send_otp(request):
    """Validate new user data and email an OTP to the user's address."""
    if not request.user.is_admin:
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    form = UserCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse({
            'success': False,
            'errors': {field: list(errs) for field, errs in form.errors.items()},
        }, status=400)

    post_data = request.POST.dict()
    post_data.pop('csrfmiddlewaretoken', None)
    email = form.cleaned_data['email']
    token, otp = store_pending_registration(request.user.pk, email, post_data)

    if not send_user_creation_otp_email(email, otp, expires_minutes=OTP_TTL_SECONDS // 60):
        return JsonResponse({
            'success': False,
            'error': 'Could not send verification email. Check mail settings and try again.',
        }, status=500)

    return JsonResponse({
        'success': True,
        'verification_token': token,
        'masked_email': mask_email(email),
        'expires_in': OTP_TTL_SECONDS,
    })


@login_required
def user_create_resend_otp(request):
    """Resend OTP for a pending user registration."""
    if not request.user.is_admin:
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    token = request.POST.get('verification_token', '').strip()
    if not token:
        return JsonResponse({'success': False, 'error': 'Missing verification session.'}, status=400)

    payload, otp = resend_otp(token)
    if not payload:
        return JsonResponse({
            'success': False,
            'error': 'Verification expired. Please start again.',
        }, status=400)

    if payload['admin_id'] != request.user.pk:
        return JsonResponse({'success': False, 'error': 'Invalid verification session.'}, status=403)

    email = payload['email']
    if not send_user_creation_otp_email(email, otp, expires_minutes=OTP_TTL_SECONDS // 60):
        return JsonResponse({
            'success': False,
            'error': 'Could not resend verification email.',
        }, status=500)

    return JsonResponse({
        'success': True,
        'masked_email': mask_email(email),
        'expires_in': OTP_TTL_SECONDS,
    })


def _create_user_from_form(form, request):
    """Save user, send welcome email, and write audit log."""
    user = form.save()
    password = form.cleaned_data['password1']
    login_url = request.build_absolute_uri(reverse('accounts:login'))
    email_sent = send_account_created_email(user, password, login_url)
    AuditLog.objects.create(
        user=request.user, action='CREATE',
        model_name='User', object_id=user.pk,
        details=f'Created user: {user.username} (email verified)'
        + ('' if email_sent else ' (welcome email failed)'),
    )
    return user, email_sent


@login_required
def user_create_verify(request):
    """Verify OTP and create the user account."""
    if not request.user.is_admin:
        return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Method not allowed.'}, status=405)

    token = request.POST.get('verification_token', '').strip()
    otp = request.POST.get('otp', '').strip()
    if not token or not otp:
        return JsonResponse({
            'success': False,
            'errors': {'otp': ['Enter the verification code from the email.']},
        }, status=400)

    post_data, error = verify_otp(token, otp, request.user.pk)
    if error:
        return JsonResponse({
            'success': False,
            'errors': {'otp': [error]},
        }, status=400)

    form = UserCreateForm(post_data)
    if not form.is_valid():
        return JsonResponse({
            'success': False,
            'error': 'Registration data is no longer valid. Please start again.',
            'errors': {field: list(errs) for field, errs in form.errors.items()},
        }, status=400)

    user, email_sent = _create_user_from_form(form, request)
    payload = {'success': True, 'user': _serialize_user(user)}
    if not email_sent:
        payload['email_warning'] = 'User created, but the welcome email could not be sent.'
    return JsonResponse(payload)


@login_required
def user_create(request):
    """Create a new user (Admin only). Requires prior OTP verification."""
    if not request.user.is_admin:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('core:dashboard')

    if request.method == 'GET':
        return redirect('users:user_list')

    return JsonResponse({
        'success': False,
        'error': 'Email verification is required. Send and confirm the OTP first.',
    }, status=400)


@login_required
def user_edit(request, pk):
    """Edit an existing user (Admin only). Supports AJAX from the user list modal."""
    if not request.user.is_admin:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': False, 'error': 'Access denied.'}, status=403)
        messages.error(request, 'Access denied.')
        return redirect('core:dashboard')

    user = get_object_or_404(User, pk=pk)

    if request.method == 'GET':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'user': _serialize_user(user)})
        return redirect(f'{reverse("users:user_list")}?edit={pk}')

    form = UserEditForm(request.POST, instance=user)
    if form.is_valid():
        user = form.save()
        AuditLog.objects.create(
            user=request.user, action='UPDATE',
            model_name='User', object_id=user.pk,
            details=f'Updated user: {user.username}'
        )
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'user': _serialize_user(user)})
        messages.success(request, f'User {user.username} updated.')
        return redirect('users:user_list')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': False,
            'errors': {field: list(errs) for field, errs in form.errors.items()},
        }, status=400)

    messages.error(request, 'Could not update user. Please try again.')
    return redirect('users:user_list')


@login_required
def user_delete(request, pk):
    """Deactivate a user (Admin only)."""
    if not request.user.is_admin:
        messages.error(request, 'Access denied.')
        return redirect('core:dashboard')

    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        user.is_active = False
        user.save()
        AuditLog.objects.create(
            user=request.user, action='DEACTIVATE',
            model_name='User', object_id=user.pk,
            details=f'Deactivated user: {user.username}'
        )
        messages.success(request, f'User {user.username} deactivated.')
    return redirect('users:user_list')

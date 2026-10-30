import pytest
from django.urls import reverse

from accounts import capabilities as caps
from accounts.models import Capability, EmployeeProfile, Role
from accounts.permissions import has_capability, scope_queryset, visible_user_ids

pytestmark = pytest.mark.django_db

ADMIN_ONLY_GET = [
    "accounts:user_list", "accounts:user_create", "accounts:login_history", "accounts:role_list",
    "core:settings_home", "core:numbering", "core:lookups", "core:audit_log",
]


@pytest.mark.parametrize("role", [caps.DIRECTOR, caps.ACCOUNTS, caps.ENGINEER, caps.COORDINATOR])
@pytest.mark.parametrize("url_name", ADMIN_ONLY_GET)
def test_non_admins_get_403_on_admin_pages(make_user, login, role, url_name):
    client = login(make_user(role))
    assert client.get(reverse(url_name)).status_code == 403


@pytest.mark.parametrize("url_name", ADMIN_ONLY_GET)
def test_admin_can_open_admin_pages(admin_user, login, url_name):
    assert login(admin_user).get(reverse(url_name)).status_code == 200


def test_direct_post_by_engineer_is_blocked(make_user, login):
    """Typing the URL or sending a crafted POST is blocked, not just hidden."""
    engineer = make_user(caps.ENGINEER)
    other = make_user(caps.COORDINATOR)
    client = login(engineer)
    r1 = client.post(reverse("accounts:user_toggle_active", args=[other.profile.pk]))
    r2 = client.post(reverse("accounts:user_reset_password", args=[other.profile.pk]),
                     {"temporary_password": "Strong-Hack-Pass-11"})
    r3 = client.post(reverse("accounts:role_edit", args=[Role.objects.get(code=caps.ENGINEER).pk]),
                     {"name": "Sales Engineer", "max_accounts": 9, "data_scope": "all"})
    assert (r1.status_code, r2.status_code, r3.status_code) == (403, 403, 403)
    other.refresh_from_db()
    assert other.is_active
    assert Role.objects.get(code=caps.ENGINEER).max_accounts == 2


def test_sidebar_shows_only_permitted_items(make_user, admin_user, login):
    engineer_page = login(make_user(caps.ENGINEER)).get(reverse("core:dashboard")).content.decode()
    admin_page = login(admin_user).get(reverse("core:dashboard")).content.decode()
    assert "User Management" not in engineer_page and "Audit Log" not in engineer_page
    assert "Collections" not in engineer_page  # engineers have no collections access by default
    assert "User Management" in admin_page and "Audit Log" in admin_page


def test_accounts_role_has_no_lead_or_quotation_access(make_user):
    user = make_user(caps.ACCOUNTS)
    assert not has_capability(user, "leads.view")
    assert not has_capability(user, "quotations.approve")
    assert has_capability(user, "payments.manage")


def test_only_owner_director_and_admin_hold_the_approve_permission(make_user):
    # the permission; who may actually decide is narrowed further by owner.rules (tested in test_owner_features)
    allowed = {r.code for r in Role.objects.filter(capabilities__code="quotations.approve")}
    assert allowed == {caps.OWNER, caps.ADMIN, caps.DIRECTOR}


def test_removing_capability_takes_effect(make_user, login):
    director = make_user(caps.DIRECTOR)
    role = director.profile.role
    role.capabilities.remove(Capability.objects.get(code="dashboard.view"))
    fresh = EmployeeProfile.objects.get(pk=director.profile.pk).user
    assert not has_capability(fresh, "dashboard.view")


def test_admin_role_cannot_lose_admin_capabilities(admin_user, login):
    role = Role.objects.get(code=caps.ADMIN)
    client = login(admin_user)
    response = client.post(reverse("accounts:role_edit", args=[role.pk]), {
        "name": role.name, "description": role.description, "max_accounts": 1, "data_scope": "all",
        "capabilities": [Capability.objects.get(code="dashboard.view").pk],
    })
    assert response.status_code == 200
    assert role.capabilities.filter(code="users.manage").exists()


def test_record_scope_by_role(make_user, admin_user):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    eng1 = make_user(caps.ENGINEER)
    eng2 = make_user(caps.ENGINEER)
    coord = make_user(caps.COORDINATOR)
    coord.profile.team_members.add(eng1.profile)

    assert visible_user_ids(admin_user) is None
    assert visible_user_ids(eng1) == {eng1.id}
    assert visible_user_ids(coord) == {coord.id, eng1.id}
    # scope_queryset applied to any model with an owner field (users used here as the example model)
    qs = scope_queryset(User.objects.all(), eng2, owner_fields=("id",))
    assert list(qs) == [eng2]

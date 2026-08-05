from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, SimpleTestCase

from issues.admin import ARCHIVED_ISSUE_STATUSES, ArchivedIssueAdmin, IssueAdmin
from issues.models import ArchivedIssue, DEFAULT_ASSIGNED_USER_ID, Issue


class IssueDefaultAssigneeTest(SimpleTestCase):
    def test_new_issues_default_to_the_standard_assignee(self):
        self.assertEqual(Issue().assigned_to_id, DEFAULT_ASSIGNED_USER_ID)

    def test_admin_prefills_the_standard_assignee(self):
        admin = IssueAdmin(Issue, AdminSite())
        field = admin.formfield_for_foreignkey(
            Issue._meta.get_field("assigned_to"),
            RequestFactory().get("/"),
        )

        self.assertEqual(field.initial, DEFAULT_ASSIGNED_USER_ID)

    def test_archived_issues_use_a_dedicated_proxy_admin(self):
        self.assertTrue(ArchivedIssue._meta.proxy)
        self.assertEqual(ArchivedIssueAdmin._archived_state, True)
        self.assertEqual(
            ARCHIVED_ISSUE_STATUSES,
            (Issue.Status.RESOLVED, Issue.Status.CLOSED),
        )

    def test_working_and_archive_views_filter_by_terminal_status(self):
        request = RequestFactory().get("/")
        working_sql, working_params = IssueAdmin(Issue, AdminSite()).get_queryset(request).query.sql_with_params()
        archive_sql, archive_params = ArchivedIssueAdmin(ArchivedIssue, AdminSite()).get_queryset(request).query.sql_with_params()

        self.assertIn("NOT", working_sql)
        self.assertIn("IN", archive_sql)
        self.assertEqual(working_params, archive_params)
        self.assertEqual(set(archive_params), set(ARCHIVED_ISSUE_STATUSES))

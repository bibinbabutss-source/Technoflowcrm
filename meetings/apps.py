from django.apps import AppConfig


class MeetingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "meetings"
    verbose_name = "Sales meetings"

    def ready(self):
        from core.audit import track_model
        from core.crud import Column
        from core.registry import register_customer_section

        from .models import Meeting
        from .services import visible_meetings

        track_model(Meeting)

        def customer_meetings(customer, user):
            return visible_meetings(user, customer.meetings.select_related("held_by", "lead", "opportunity"))

        register_customer_section("meetings", "Meetings", "leads.view", customer_meetings, [
            Column("Date", "meeting_date", date=True, link=True), Column("Type", "get_meeting_type_display"),
            Column("Held by", "held_by"), Column("Summary", lambda m: m.summary[:80]),
            Column("Next follow-up", "next_follow_up", date=True)], order=15)

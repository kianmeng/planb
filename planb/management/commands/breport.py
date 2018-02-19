from dateutil.relativedelta import relativedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import ugettext as _

from planb.models import HostConfig


class Command(BaseCommand):
    help = 'Email backup report'

    def handle(self, *args, **options):
        qs = (
            HostConfig.objects
            .filter(hostgroup__notify_email__contains='@')
            .select_related('hostgroup')
            .order_by('hostgroup__name', 'friendly_name'))
        self.send_monthly_reports(qs)

    def send_monthly_reports(self, qs):
        last_month = timezone.now() - relativedelta(days=25)
        qs = qs.filter(
            Q(hostgroup__last_monthly_report=None) |
            Q(hostgroup__last_monthly_report__lt=last_month))

        lastgroup = None
        hosts = []
        for host in qs:
            if lastgroup != host.hostgroup:
                if lastgroup is not None:
                    self.email_hostgroup(lastgroup, hosts)
                lastgroup = host.hostgroup
                hosts = []
            hosts.append(host)

        if lastgroup is not None:
            self.email_hostgroup(lastgroup, hosts)

    def email_hostgroup(self, hostgroup, hosts):
        context = {
            'hostgroup': hostgroup,
            'hosts': hosts,
            'company_name': settings.COMPANY_NAME,
            'company_email': settings.COMPANY_EMAIL,
        }
        subject = _('Plan B backup report for %s') % (hostgroup.name,)
        message = render_to_string('planb/report_email_body.txt', context)
        for recipient in hostgroup.notify_email:
            recipient = recipient.strip()
            if not recipient:
                continue
            self.stdout.write(
                'Sending report for {} to {}'.format(hostgroup, recipient))
            send_mail(
                subject=subject, message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient],
                fail_silently=False,
                html_message=None,
            )
        hostgroup.last_monthly_report = timezone.now()
        hostgroup.save(update_fields=['last_monthly_report'])

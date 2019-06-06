# Generated by Django 2.0.4 on 2019-06-06 14:02

from django.db import migrations, models
import django.db.models.deletion
import planb.fields
import planb.transport_rsync.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('planb', '0011_hostconfig_to_fileset'),
    ]

    operations = [
        migrations.CreateModel(
            name='Config',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('host', models.CharField(max_length=254)),
                ('src_dir', models.CharField(default='/', max_length=254)),
                ('includes', planb.fields.FilelistField(default='data etc home root srv usr/local/bin var/backups var/lib/dpkg/status* var/lib/psdiff.db* var/spool/cron var/www', max_length=1023)),
                ('excludes', planb.fields.FilelistField(blank=True, max_length=1023)),
                ('transport', planb.transport_rsync.models.TransportChoices(choices=[(0, 'ssh (default)'), (1, 'rsync (port 873)')], default=0)),
                ('user', models.CharField(default='root', max_length=254)),
                ('use_sudo', models.BooleanField(default=False)),
                ('use_ionice', models.BooleanField(default=False)),
                ('rsync_path', models.CharField(default='/usr/bin/rsync', max_length=31)),
                ('ionice_path', models.CharField(blank=True, default='/usr/bin/ionice', max_length=31)),
                ('flags', models.CharField(default='-az --numeric-ids --stats --delete', help_text='Default "-az --delete", add "--no-perms --chmod=D0700,F600" for (windows) hosts without permission bits, add "--iconv=utf8,latin1" for hosts with files with legacy (Latin-1) encoding.', max_length=511)),
                ('fileset', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='planb.Fileset')),
            ],
        ),
    ]

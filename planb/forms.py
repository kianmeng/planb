from django import forms
from django.apps import apps
from django.conf import settings


class FilesetRefForm(forms.ModelForm):
    """
    Generate FilesetRefForm tailored to the supplied class; so sorting
    of the Filesets works.

    Use in your admin class. For example:

        from django.forms import modelform_factory
        from planb.forms import FilesetRefForm

        class MyModel(models.Model):
            fileset = models.OneToOneField(Fileset)

        class MyModelAdmin(admin.ModelAdmin):
            form = modelform_factory(MyModel, form=FilesetRefForm)
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if 'fileset' in self.fields:
            # Order.
            self.fields['fileset'].queryset = (
                self.fields['fileset'].queryset.order_by('friendly_name'))

            # Get IDs of used filesets.
            ids = set()
            for transport_class_name in settings.PLANB_TRANSPORTS:
                transport_class = apps.get_model(transport_class_name)
                ids.update(transport_class.objects.values_list(
                    'fileset', flat=True))

            # Don't list used filesets.
            # NOTE: This is not a fool-proof way to avoid
            # MultipleObjectsReturned. But it will provide a better
            # interface.
            self.fields['fileset'].queryset = (
                self.fields['fileset'].queryset.exclude(id__in=ids))

    class Meta:
        fields = '__all__'

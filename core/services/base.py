from abc import ABC

from django.db import transaction


class BaseService(ABC):
    model = None

    def get_queryset(self):
        if self.model is None:
            raise ValueError("BaseService requires a model.")
        return self.model.objects.all()

    def get(self, **lookup):
        return self.get_queryset().get(**lookup)

    def list(self, **filters):
        return self.get_queryset().filter(**filters)

    @transaction.atomic
    def create(self, **data):
        if self.model is None:
            raise ValueError("BaseService requires a model.")
        return self.model.objects.create(**data)

    @transaction.atomic
    def update(self, instance, **data):
        for field, value in data.items():
            setattr(instance, field, value)
        instance.save()
        return instance

    @transaction.atomic
    def delete(self, instance):
        instance.delete()

from rest_framework import status
from rest_framework.test import APITestCase

from contact.models import Contact


class ContactApiTests(APITestCase):
    def test_public_contact_cannot_set_is_read(self):
        response = self.client.post(
            "/api/contact/",
            {
                "name": "Visitor",
                "email": "visitor@example.com",
                "message": "Hello there",
                "is_read": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        contact = Contact.objects.get(pk=response.data["id"])
        self.assertFalse(contact.is_read)

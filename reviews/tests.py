from rest_framework import status
from rest_framework.test import APITestCase

from reviews.models import Reviews
from users.models import User


class ReviewApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="reviewer@example.com", password="pass1234")

    def test_create_review_uses_authenticated_user(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            "/api/reviews/",
            {
                "user": 9999,
                "title": "Solid monitoring",
                "rating": 5,
                "comments": "Very useful",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        review = Reviews.objects.get(pk=response.data["id"])
        self.assertEqual(review.user_id, self.user.id)

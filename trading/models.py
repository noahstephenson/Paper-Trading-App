from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import models


User = get_user_model()


class Trade(models.Model):
    # Each paper trade belongs to one logged-in user.
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # These choices limit trade_type to the two actions we support.
    BUY = 'BUY'
    SELL = 'SELL'
    TRADE_TYPE_CHOICES = [
        (BUY, 'Buy'),
        (SELL, 'Sell'),
    ]

    # The stock symbol the user traded, like AAPL or MSFT.
    ticker = models.CharField(max_length=10)
    # This tells us whether the trade was a buy or a sell.
    trade_type = models.CharField(max_length=4, choices=TRADE_TYPE_CHOICES)
    # How many shares were traded.
    quantity = models.PositiveIntegerField()
    # The price per share at the time of the trade.
    price = models.DecimalField(max_digits=10, decimal_places=2)
    # Save when the trade was created.
    created_at = models.DateTimeField(auto_now_add=True)
    # Optional note explaining the trader's reasoning.
    notes = models.TextField(blank=True, default="")

    @property
    def total(self):
        return self.quantity * self.price

    def __str__(self):
        # This gives each trade a readable name in the Django admin.
        return f'{self.trade_type} {self.quantity} shares of {self.ticker}'


class WatchlistItem(models.Model):
    # Each watchlist entry belongs to one user.
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # The stock symbol the user wants to track, like AAPL or TSLA.
    ticker = models.CharField(max_length=10)
    # Recorded automatically when the ticker is added.
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Prevents adding the same ticker twice for the same user.
        unique_together = ('user', 'ticker')

    def __str__(self):
        return f"{self.user.username} watching {self.ticker}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    cash_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('100000.00'))
    starting_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('100000.00'))

    def __str__(self):
        return f"{self.user.username} profile"

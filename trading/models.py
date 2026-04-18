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

    @property
    def total(self):
        return self.quantity * self.price

    def __str__(self):
        # This gives each trade a readable name in the Django admin.
        return f'{self.trade_type} {self.quantity} shares of {self.ticker}'


class WatchlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=10)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'ticker')

    def __str__(self):
        return f"{self.user.username} watching {self.ticker}"

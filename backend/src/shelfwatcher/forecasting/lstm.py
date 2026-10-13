import torch
import torch.nn as nn
from typing import List


class QuantileLoss(nn.Module):
    """
    Pinball (Quantile) Loss for multi-quantile regression: q in {0.1, 0.5, 0.9}.
    """

    def __init__(self, quantiles: List[float] = [0.1, 0.5, 0.9]):
        super().__init__()
        self.quantiles = quantiles

    def forward(self, preds: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """
        preds: (batch, horizon, num_quantiles)
        target: (batch, horizon)
        """
        losses = []
        for i, q in enumerate(self.quantiles):
            err = target - preds[:, :, i]
            loss = torch.max((q - 1) * err, q * err)
            losses.append(loss.mean())
        return torch.stack(losses).sum()


class QuantileLSTMForecaster(nn.Module):
    """
    Global Multi-Quantile LSTM Forecaster with SKU Embedding (context.md Section 9.5).
    Predicts P10, P50, and P90 demand trajectories over a 7-day horizon.
    """

    def __init__(
        self,
        num_skus: int = 20,
        sku_embed_dim: int = 8,
        num_features: int = 4,  # log1p(units), day_of_week, promo_flag, price_norm
        hidden_dim: int = 64,
        num_layers: int = 2,
        horizon: int = 7,
        num_quantiles: int = 3
    ):
        super().__init__()
        self.horizon = horizon
        self.num_quantiles = num_quantiles

        # SKU Identity Embedding
        self.sku_embed = nn.Embedding(num_skus + 1, sku_embed_dim)

        # LSTM Layer
        input_dim = num_features + sku_embed_dim
        self.lstm = nn.LSTM(
            input_size=input_dim,
            hidden_size=hidden_dim,
            num_layers=num_layers,
            batch_first=True,
            dropout=0.1 if num_layers > 1 else 0.0
        )

        # Quantile Output Head: outputs (horizon * num_quantiles)
        self.fc = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, horizon * num_quantiles)
        )

    def forward(self, x: torch.Tensor, sku_idx: torch.Tensor) -> torch.Tensor:
        """
        x: (batch, seq_len, num_features)
        sku_idx: (batch)
        returns: (batch, horizon, num_quantiles)
        """
        batch_size, seq_len, _ = x.shape

        # Replicate SKU embedding across all sequence timesteps
        embed = self.sku_embed(sku_idx).unsqueeze(1).repeat(1, seq_len, 1)
        lstm_input = torch.cat([x, embed], dim=-1)

        out, (hn, cn) = self.lstm(lstm_input)
        # Use last hidden state
        last_hidden = out[:, -1, :]
        raw_preds = self.fc(last_hidden)

        # Reshape to (batch, horizon, num_quantiles)
        preds = raw_preds.view(batch_size, self.horizon, self.num_quantiles)
        return preds

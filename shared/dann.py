"""Task 2 DANN: adversarial alignment of 512-D ResNet-18 features."""
import math

from torch import nn
from torch.autograd import Function


class _GradientReversal(Function):
    @staticmethod
    def forward(ctx, features, strength):
        ctx.strength = float(strength)
        return features.view_as(features)

    @staticmethod
    def backward(ctx, gradient):
        return -ctx.strength * gradient, None


def reverse_gradient(features, strength):
    """Identity forward; negate and scale only the gradient entering features."""
    return _GradientReversal.apply(features, strength)


def reversal_strength(progress, maximum=1.0):
    """p is progress through the fixed maximum training budget, not early stopping.

    alpha(p) = maximum * (2 / (1 + exp(-10*p)) - 1).
    The standard schedule approaches (rather than exactly reaches) maximum.
    """
    if not 0 <= progress <= 1:
        raise ValueError('Training progress must be in [0, 1].')
    return float(maximum) * (2.0 / (1.0 + math.exp(-10.0 * progress)) - 1.0)


class DomainDiscriminator(nn.Sequential):
    def __init__(self, input_dim=512):
        super().__init__(nn.Linear(input_dim, 256), nn.ReLU(), nn.Dropout(0.5), nn.Linear(256, 2))


def train_dann(data_root, split_path, output_dir, config=None):
    from .source_erm import CONFIG, train_pacs
    cfg = dict(CONFIG)
    cfg.update(target_batch_size=24, max_grl_strength=1.0, domain_loss_weight=1.0,
               discriminator_hidden=256, discriminator_dropout=0.5,
               grl_schedule='max_strength * (2 / (1 + exp(-10*p)) - 1)',
               progress_definition='zero_based_update / (maximum_total_updates - 1)')
    if config is not None:
        cfg.update(config)
    if cfg['target_batch_size'] != 24 or cfg['batch_per_domain'] != 8:
        raise ValueError('Use 8 examples per source domain and 24 target examples.')
    if cfg['domain_loss_weight'] != 1.0:
        raise ValueError('The required DANN domain-loss weight is 1.')
    if cfg['discriminator_hidden'] != 256 or cfg['discriminator_dropout'] != 0.5:
        raise ValueError('The required discriminator has 256 hidden units and dropout 0.5.')
    if not 0 < cfg['max_grl_strength'] <= 1:
        raise ValueError('Maximum reversal strength must be in (0, 1].')
    return train_pacs(data_root, split_path, output_dir, cfg, method='dann')

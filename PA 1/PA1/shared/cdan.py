"""Task 2 CDAN: full feature/probability outer product, without detachment."""
import torch


def conditional_features(features, probabilities):
    """vec(f outer p): [B,512] x [B,7] -> [B,3584].

    Both inputs remain in the autograd graph. Gradient reversal is applied to
    this joint representation by the common training loop, so the domain loss
    reaches both the feature backbone and the class-probability path.
    """
    if features.ndim != 2 or probabilities.ndim != 2:
        raise ValueError('Expected feature and probability matrices.')
    if features.shape[0] != probabilities.shape[0]:
        raise ValueError('Feature and probability batch sizes must match.')
    return torch.bmm(features.unsqueeze(2), probabilities.unsqueeze(1)).flatten(1)


def train_cdan(data_root, split_path, output_dir, config=None):
    from .source_erm import CONFIG, train_pacs
    cfg = dict(CONFIG)
    cfg.update(target_batch_size=24, max_grl_strength=1.0, domain_loss_weight=1.0,
               discriminator_hidden=256, discriminator_dropout=0.5,
               grl_schedule='max_strength * (2 / (1 + exp(-10*p)) - 1)',
               progress_definition='zero_based_update / (maximum_total_updates - 1)',
               conditioning='full_feature_probability_outer_product',
               discriminator_input_dim=3584, entropy_conditioning=False,
               detach_features=False, detach_probabilities=False)
    if config is not None:
        cfg.update(config)
    required = dict(target_batch_size=24, batch_per_domain=8,
                    domain_loss_weight=1.0, discriminator_hidden=256,
                    discriminator_dropout=0.5, discriminator_input_dim=3584,
                    conditioning='full_feature_probability_outer_product',
                    entropy_conditioning=False, detach_features=False,
                    detach_probabilities=False)
    for key, value in required.items():
        if cfg[key] != value:
            raise ValueError(f'The required CDAN comparison uses {key}={value!r}.')
    if not 0 < cfg['max_grl_strength'] <= 1:
        raise ValueError('Maximum reversal strength must be in (0, 1].')
    return train_pacs(data_root, split_path, output_dir, cfg, method='cdan')

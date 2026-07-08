# Wenling hand luck neighbor-average runtime

This runtime is embedded in the LAN host and Android package. It only uses the
Python standard library and does not require the original self-play data.

`hand_luck_neighbor.py` and `hand_luck_neighbor_model.json` are copied from
`files-mentioned-by-the-user-md/dist/hand_luck_neighbor_average_settlement_fan_runtime.zip`.
The public entrypoint remains:

```python
from hand_luck import load_hand_luck_scorer
```

## Required fields

- `de_draws`
- `fan_flower_draws`
- `opening_shanten`
- `final_shanten`
- `normal_draw_count`
- `open_claim_count`
- `opening_leizi_distance`
- `final_leizi_distance`

## Optional fields

- `seat`
- `supplement_draw_count`
- `win_type`
- `leizi_win`
- `zimo_de`
- `gang_flower`
- `rob_gang`

The compatibility wrapper also exposes the legacy settlement fields
`predicted_point_delta`, `luck_impact`, and `categories`; for this model those
fields are derived from the neighbor-average `model_score` and normalized input
features.

For this runtime, `fan_flower_draws` keeps its historical parameter name but is
the settlement fan count from `字牌花` and `门风花` fan items. It is not the raw
number of non-de flower replacement draws.

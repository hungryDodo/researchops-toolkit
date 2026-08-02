# Academic figure protocol

## Choose the figure's job

- **motivated example**: make the pain point and why existing behavior fails immediately visible;
- **system/method overview**: expose components, data/control flow, boundaries, and the novel mechanism;
- **execution/timeline**: show ordering, overlap, synchronization, or resource occupancy;
- **experimental result**: answer one comparison or trend with honest uncertainty;
- **ablation/sensitivity**: isolate mechanism contribution and operating range;
- **supporting diagnostic**: explain why a result occurs without overstating causality.

One figure should have one dominant question. Do not combine unrelated figure roles merely to save space.

## Integrity and readability

- data plots are generated from machine-readable derived data, never manually edited values;
- axes, normalization, aggregation, exclusions, sample count, and uncertainty are explicit;
- use direct labels and redundant encodings where possible;
- test at final single-/double-column size and in grayscale/color-blind simulation;
- retain editable source plus vector PDF/SVG when possible;
- captions state the question, conditions, metric, direction, and bounded conclusion.

At least one independent viewer should be able to answer the intended question from the rendered figure without oral explanation.

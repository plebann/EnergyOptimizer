# Decision Engine Diagrams (Control File)

This file provides a high-level view of decision engine actions and their possible outcomes. Detailed flowcharts live in the action docs.

## High-Level Outcomes

```mermaid
flowchart LR
  subgraph MorningChargeGroup[ ]
    direction TB
    MorningCharge[Morning Charge action]
    MorningCharge_note[Note: runs at 04:00]
    MorningCharge --> MorningCharge_note
  end

  MorningCharge --> MorningCharge_outcomes(( ))
  MorningCharge_outcomes --> MorningCharge_no_action[No action]
  MorningCharge_outcomes --> MorningCharge_charge[Charge scheduled]

  subgraph AfternoonChargeGroup[ ]
    direction TB
    AfternoonCharge[Afternoon Charge action]
    AfternoonCharge_note[Note: runs at tariff end]
    AfternoonCharge --> AfternoonCharge_note
  end

  AfternoonCharge --> AfternoonCharge_outcomes(( ))
  AfternoonCharge_outcomes --> AfternoonCharge_no_action[No action]
  AfternoonCharge_outcomes --> AfternoonCharge_charge[Charge scheduled]

  subgraph EveningBehaviorGroup[ ]
    direction TB
    EveningBehavior[Evening Behavior action]
    EveningBehavior_note[Note: runs at 22:00]
    EveningBehavior --> EveningBehavior_note
  end

  EveningBehavior --> EveningBehavior_outcomes(( ))
  EveningBehavior_outcomes --> EveningBehavior_balancing[Balancing mode]
  EveningBehavior_outcomes --> EveningBehavior_preservation[Preservation mode]
  EveningBehavior_outcomes --> EveningBehavior_normal[Normal behavior]
  EveningBehavior_outcomes --> EveningBehavior_no_action[No action]

  style MorningChargeGroup fill:transparent,stroke:transparent
  style AfternoonChargeGroup fill:transparent,stroke:transparent
  style EveningBehaviorGroup fill:transparent,stroke:transparent
```

## Detailed Diagrams

- Morning: [docs/Morning_Charge_Action.md](docs/Morning_Charge_Action.md)
- Afternoon: [docs/Afternoon_Charge_Action.md](docs/Afternoon_Charge_Action.md)
- Evening: [docs/Evening_Behavior_Action.md](docs/Evening_Behavior_Action.md)

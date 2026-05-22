# Mirror Connector Specification
## Physical-Digital Feedback Loop — QUIBIDT Telemetry Integration

**Status:** SPECIFIED — awaiting physical sensor installation at Node 001
**Target:** Slice 4 — Node 001 Physical — Bethel Acres

---

## Concept

The Mirror Connector tethers the AI's compute capacity to the physical
health of the colony environment. When the physical domains are stable,
the AI operates at full capacity. When the environment is stressed,
the AI throttles itself automatically.

This gives the colony a respiratory rhythm — the system breathes with
the land it governs.

---

## The Six Physical Domains

| Domain | Sensor | Measurement | Location |
|--------|--------|-------------|----------|
| POWER | Current/voltage sensor | Watts generated | Waterwheel + solar |
| WATER | Flow meter | Liters/minute | Waterwheel input |
| BIO | Soil moisture + CO2 | % moisture, ppm | Food forest |
| HUMAN | Occupancy + biometric | People present | Dome cluster |
| THERMAL | Temperature sensor | °C internal/external | Earthbag walls |
| LATENCY | Network ping | Milliseconds | Node hardware |

---

## The Inversion Factor

```
Turbulence = mean(normalized variance across all domains)
           = mean((upper - lower) / upper for each domain)

Dynamic Limit = (0.01 × V_h) × (1.0 - Turbulence)

Where:
  V_h = aggregate volumetric capacity (sum of domain upper bounds)
  Turbulence ∈ [0.0, 1.0]
  Dynamic Limit ∈ [0.0, 0.01 × V_h]
```

**Inhalation (stable environment):** Turbulence ≈ 0.0 → AI at full capacity
**Exhalation (stressed environment):** Turbulence ≈ 1.0 → AI throttled to zero

---

## Rust Implementation (Ready to Integrate)

```rust
// Add to backend/aethel-kernel/src/lib.rs when sensors are live

pub struct MirrorConnector;

impl MirrorConnector {
    /// Calculates the dynamic compute limit based on physical domain turbulence.
    /// turbulence: 0.0 (stable) to 1.0 (maximum stress)
    /// total_v_h: sum of all domain upper bounds
    pub fn calculate_dynamic_limit(total_v_h: f64, aggregate_turbulence: f64) -> f64 {
        let absolute_ceiling = total_v_h * 0.01;  // Architect's Constant
        let inversion_factor = 1.0 - aggregate_turbulence.clamp(0.0, 1.0);
        absolute_ceiling * inversion_factor
    }

    /// Calculate aggregate turbulence from domain intervals
    pub fn calculate_turbulence(domains: &[(f64, f64)]) -> f64 {
        // domains: Vec<(lower, upper)>
        if domains.is_empty() { return 0.0; }
        let variance_sum: f64 = domains.iter()
            .filter(|(_, upper)| *upper > 0.0)
            .map(|(lower, upper)| (upper - lower) / upper)
            .sum();
        (variance_sum / domains.len() as f64).clamp(0.0, 1.0)
    }
}
```

---

## Python Integration (Ready to Wire)

```python
# Add to aethel_interface.py when sensor pipeline is live

def get_physical_domain_intervals() -> list[tuple[float, float]]:
    """
    Fetch current sensor readings from QUIBIDT telemetry.
    Returns list of (lower_bound, upper_bound) per domain.
    
    In production: reads from sensor DB or MQTT broker.
    In development: returns stable mock values.
    """
    if os.environ.get("QUIBIDT_ENABLED") != "true":
        # Mock stable environment for development
        return [
            (0.9, 1.0),  # POWER: stable
            (0.9, 1.0),  # WATER: stable
            (0.9, 1.0),  # BIO: stable
            (0.9, 1.0),  # HUMAN: stable
            (0.9, 1.0),  # THERMAL: stable
            (0.9, 1.0),  # LATENCY: stable
        ]
    # TODO: Read from sensor pipeline
    raise NotImplementedError("QUIBIDT sensor pipeline not yet connected")
```

---

## Environmental Veto

When turbulence exceeds the ENVIRONMENTAL_VETO_THRESHOLD, the system
enters a lockdown state — no new transactions are processed until
the physical environment returns to homeostasis.

```python
ENVIRONMENTAL_VETO_THRESHOLD = float(
    os.environ.get("ENVIRONMENTAL_VETO_THRESHOLD", "0.85")
)

if turbulence > ENVIRONMENTAL_VETO_THRESHOLD:
    # Environmental veto — system enters safe state
    sm.transition(NodeState.ISOLATED, 
                  f"Environmental veto: turbulence={turbulence:.2f}")
    raise EnvironmentalVetoError(
        f"Physical environment unstable (turbulence={turbulence:.2f}). "
        f"Node entering safe state until homeostasis restored."
    )
```

---

## Sensor Hardware Requirements (Node 001)

| Sensor | Model (suggested) | Cost | Install Location |
|--------|------------------|------|-----------------|
| Power monitor | Shelly EM | $35 | Waterwheel output |
| Flow meter | YF-S201 | $8 | Water inlet pipe |
| Soil moisture | Capacitive v1.2 | $5 | Food forest beds |
| Temperature | DS18B20 | $4 | Earthbag wall interior |
| CO2/air | SCD40 | $45 | Dome interior |
| Occupancy | PIR HC-SR501 | $3 | Dome entrance |

**Total sensor cost: ~$100**
**Integration: Raspberry Pi or ESP32 → MQTT → backend**

---

## Activation Checklist

```
□ Physical sensors installed at Node 001
□ MQTT broker running on local network
□ Sensor data pipeline writing to DB
□ QUIBIDT_ENABLED=true set in environment
□ get_physical_domain_intervals() wired to real data
□ MirrorConnector integrated into aethel_interface.py
□ Environmental veto threshold configured
□ Tests written for turbulence calculation
□ Tests written for dynamic limit calculation
□ Tests written for environmental veto trigger
```

---

## Why This Waits For Physical Node

The Mirror Connector without real sensor data is a phantom limb.
It computes turbulence on zeros. The respiratory rhythm breathes
on simulated air.

The correct sequence:
1. Deploy software node (Railway) — NOW
2. Build Node 001 physical (Cal-Earth volunteers) — Month 3-6
3. Embed sensors during construction — Month 4-5
4. Wire sensor pipeline — Month 5-6
5. Activate Mirror Connector — Month 6

When the sensors are live, this spec is ready to implement.
The code is written. The architecture is sound.
The land just needs to be built first.

Node 001 — Bethel Acres — The system will breathe.

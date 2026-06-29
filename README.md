# SortIQ
# ♻️ SORTiQ: AI-based Value Component Recovery

SORTiQ is an intelligent pre-sorting system designed to close the value-recovery gap in e-waste recycling. By moving from destructive bulk shredding to a targeted, component-level depopulation strategy, SORTiQ improves the purity and recovery of Critical Raw Materials (CRMs).

## 🚀 Project Overview
* **Aim:** Automated detection and recovery of high-value components (PCBs, magnets, RAM) from e-waste streams for targeted recycling or direct reuse.
* **Research Focus:** Investigating the systems-thinking approach to e-waste recovery, specifically managing data uncertainty propagation, industrial safety requirements, and economic trade-offs in automated sorting pipelines.

## 🏗️ Technical Architecture
### Vision & Inference
* **Detection:** Hybrid model architecture utilizing **RT-DETRv2** for high-precision component identification, complemented by **YOLOv8** for general object flow.
* **Optimization:** Deployed via **ONNX inference** to ensure the latency requirements of high-speed sorting.
* **Tracking:** Object tracking implemented using **Kalman Filters** and the **Hungarian Algorithm** for robust component path prediction.

### Hardware & Sensor Fusion
* **Sensing Layer:** Integrated magnetometer arrays for flux density measurement, combined with object detection sensors for high-fidelity component validation.
* **Control Stack:** Coordinated multi-controller setup leveraging **Raspberry Pi Pico, ESP32, and Arduino**.
* **Observability:** Full-stack monitoring via **Grafana and InfluxDB**, with the environment containerized using **Docker** for reproducible deployment.

## 🔧 Engineering Post-Mortem: Real-World Lessons
The transition from PoC to an industrial-ready system required overcoming significant hardware-software integration hurdles:
* **EMI & Brownouts:** High-current actuators caused electrical noise, resulting in intermittent serial communication drops. This was mitigated by implementing a "Lazy Servo" PWM protocol to isolate signal pins during idle states.
* **Communication Resilience:** Persistent I2C handshake errors during magnetometer polling were resolved by implementing robust, auto-resetting communication wrappers.
* **Signal Fragmentation:** Asynchronous serial data streams were unified through a full-buffer-drain ingestion algorithm to ensure zero-loss synchronization between the IO layer and the vision brain.

## 🔬 Research Areas & Future Directions
SORTiQ is currently evolving into a testbed for precision depopulation research:
* **Uncertainty Propagation:** Modeling how detection confidence drops—due to occlusion or perspective changes—impacts final sorting accuracy.
* **Traceability:** Development of a framework for Digital Product Passports using QR/OCR to ensure end-to-end component visibility.
* **Economic/Regulatory Alignment:** Evaluating the complex interdependencies between sorting throughput, material purity, and compliance with the EU Critical Raw Materials Act and Right-to-Repair Directives. 
* **Systems Development Approach:** Analyzing the necessity of AI and automation by mapping the trade-offs between CapEx, OpEx, and the potential revenue uplift from high-purity CRM recovery. This research treats the recycling plant as an integrated system, where intelligent automation is the required catalyst to convert "trash into cash" while meeting stringent regulatory sustainability mandates.

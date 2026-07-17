# ADR-0001: Keep a modular monolith

- Status: Accepted
- Date: 2026-07-17

K_desk remains a single-host modular monolith with two web composition roots and durable workers.
Microservices would add deployment, data consistency and monitoring cost without a current scaling need.

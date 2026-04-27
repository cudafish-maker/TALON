# Mobile Map

Mobile should be map-first. The map is the primary field dashboard, not a
secondary screen.

## Required Layers

- Base map.
- Asset markers.
- Zone polygons.
- Mission AO and routes.
- Current selected mission context.

## Interaction

- Touch-friendly marker selection.
- Slide-up or side panel for context details.
- Quick SITREP action from map context.
- Asset create/update from map location where core policy allows.

## Constraints

- Use Android-native map rendering or another mobile-appropriate map component.
- Consume core map read models; do not duplicate joins or filtering rules.
- AO tile pre-cache remains deferred until core storage/sync policy exists.

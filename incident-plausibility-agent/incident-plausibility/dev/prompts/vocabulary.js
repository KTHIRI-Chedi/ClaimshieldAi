// Shared controlled vocabulary. The Visual Inspection and Invoice Parser agents must use the
// same part names, otherwise the invoice comparison cannot match parts.
const VOCAB = {
  PARTS: [
    'front_bumper', 'rear_bumper', 'hood', 'trunk_lid_tailgate', 'front_grille', 'radiator',
    'headlight_left', 'headlight_right', 'taillight_left', 'taillight_right',
    'fender_front_left', 'fender_front_right', 'quarter_panel_rear_left', 'quarter_panel_rear_right',
    'door_front_left', 'door_front_right', 'door_rear_left', 'door_rear_right',
    'mirror_left', 'mirror_right', 'windshield', 'rear_window', 'side_window',
    'roof', 'wheel_rim', 'tire', 'suspension', 'airbag', 'engine_component',
  ],
  SCENARIOS: [
    'rear_end_struck', 'rear_end_striking', 'side_impact', 'sideswipe', 'parking_scrape',
    'reversing_collision', 'single_vehicle_object', 'vandalism', 'glass_damage', 'weather_hail',
    'other', 'unknown',
  ],
  ZONES: [
    'front', 'front_left', 'front_right', 'left_side', 'right_side', 'rear', 'rear_left',
    'rear_right', 'roof', 'windshield', 'underbody', 'multiple', 'unknown',
  ],
  ROAD_FEATURES: [
    'roundabout', 'traffic_light', 'intersection', 'parking_lot', 'highway',
    'residential_street', 'fuel_station', 'bridge', 'tunnel',
  ],
  VEHICLE_STATES: ['moving', 'stopped_in_traffic', 'parked', 'reversing', 'unknown'],
  OTHER_PARTIES: ['vehicle', 'object', 'animal', 'person', 'vandal', 'weather', 'none', 'unknown'],
  DIRECTIONS: ['front', 'rear', 'left', 'right', 'top', 'unknown'],
  WEATHER: ['clear', 'rain', 'snow', 'ice', 'fog', 'hail', 'storm'],
  LIGHT: ['daylight', 'dusk_dawn', 'dark'],
};

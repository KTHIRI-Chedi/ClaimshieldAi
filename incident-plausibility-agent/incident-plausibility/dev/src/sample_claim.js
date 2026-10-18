// Test claim used when the workflow is run by hand from the editor.
// The orchestrator sends the same shape through "When called by orchestrator".
//
// The workflow never asks for a location: it comes with the claim. Real claims get the pin from
// the map on the claim form. To test another spot here, replace incident_lat / incident_lon:
// in Google Maps or openstreetmap.org, right-click the spot and copy its coordinates.
// Delete both lines to test with the typed address only (less precise).
return [{
  json: {
    claim_id: 'CLM-TEST-0001',
    incident_datetime: '2026-03-14T18:40:00', // local time at the incident location
    incident_lat: 36.8004, // map pin: traffic light on Avenue Habib Bourguiba, downtown Tunis
    incident_lon: 10.1866,
    incident_location: 'Avenue Habib Bourguiba, Tunis, Tunisia',
    description:
      'I was stopped at the traffic light on Avenue Habib Bourguiba when the car behind me ' +
      'hit the back of my car. It was raining heavily and already dark.',
    invoice: {
      line_items: [
        { part: 'rear_bumper' },
        { part: 'taillight_left' },
        { part: 'radiator' },
      ],
    },
  },
}];

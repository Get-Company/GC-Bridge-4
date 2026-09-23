(function () {
    "use strict";

    const distance = document.getElementById("id_distance_km");
    const rate = document.getElementById("id_rate_per_km");
    const roundTrip = document.getElementById("id_round_trip");
    const fare = document.querySelector(".field-fare_cost_display .readonly");
    const total = document.querySelector(".field-trip_total_display .readonly");

    if (!distance || !rate || !roundTrip || !fare || !total) {
        return;
    }

    const currency = new Intl.NumberFormat("de-DE", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });

    function parseDecimal(input) {
        const value = input.value.trim().replace(",", ".");
        return value === "" ? NaN : Number(value);
    }

    function update() {
        const kilometers = parseDecimal(distance);
        const eurosPerKm = parseDecimal(rate);
        if (!Number.isFinite(kilometers) || !Number.isFinite(eurosPerKm) || kilometers < 0 || eurosPerKm < 0) {
            fare.textContent = "Wird automatisch berechnet";
            total.textContent = "Wird automatisch berechnet";
            return;
        }
        fare.textContent = `${currency.format(kilometers * eurosPerKm)} EUR`;
        total.textContent = `${currency.format(kilometers * eurosPerKm * (roundTrip.checked ? 2 : 1))} EUR`;
    }

    for (const input of [distance, rate, roundTrip]) {
        input.addEventListener("input", update);
        input.addEventListener("change", update);
    }
    update();
})();

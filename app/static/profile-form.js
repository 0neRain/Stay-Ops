(function registerProfileForm(root) {
  const profileFields = Object.freeze([
    "name",
    "timezone",
    "address",
    "property_type",
    "guest_capacity",
    "bedrooms",
    "bathrooms",
    "check_in_time",
    "check_out_time",
    "wifi_network",
    "parking_instructions",
    "access_instructions",
    "house_rules",
    "amenities",
    "emergency_information",
    "local_recommendations",
  ]);
  const listFields = new Set(["house_rules", "amenities", "local_recommendations"]);

  function bulletList(items) {
    const uniqueItems = [];
    items.forEach((item) => {
      const cleaned = item.replace(/^\s*[-*+]\s*/, "").replace(/\s+/g, " ").trim();
      if (cleaned && !uniqueItems.includes(cleaned)) uniqueItems.push(cleaned);
    });
    return uniqueItems.map((item) => `- ${item}`).join("\n");
  }

  function legacyAmenityItems(value) {
    if (!value.includes("|")) return [];
    const tokens = value.split("|").map((item) => item.trim()).filter(Boolean);
    const labels = new Set(["Wi-Fi network", "Router location", "Heating", "Cooling", "Laundry"]);
    const items = [];
    for (let index = 0; index < tokens.length - 1; index += 1) {
      const label = tokens[index];
      if (!labels.has(label)) continue;
      const sentences = tokens[index + 1]
        .split(
          /(?<=[.!?])\s+|\s+(?=The kitchen has|Olive oil,|The outdoor dining|There is also a travel cot|The plunge pool|It is not heated|Children must)/,
        )
        .filter(Boolean);
      if (label !== "Wi-Fi network" && sentences.length) {
        items.push(`${label}: ${sentences.shift()}`);
        items.push(...sentences);
      }
      index += 1;
    }
    return items;
  }

  function formatProfileValue(field, value) {
    if (!listFields.has(field) || typeof value !== "string" || !value.trim()) return value;
    const existingLines = value.split(/\r?\n/).filter((line) => line.trim());
    if (existingLines.length > 1) return bulletList(existingLines);
    const amenityItems = field === "amenities" ? legacyAmenityItems(value) : [];
    if (amenityItems.length) return bulletList(amenityItems);
    const items = field === "local_recommendations"
      ? value.split(/(?<=[.!?])\s+/)
      : value.split(/;\s+(?=[A-Z0-9])/);
    return bulletList(items);
  }

  function fillHomeProfileForm(form, profile) {
    if (!form?.elements) return;
    const values = profile && typeof profile === "object" ? profile : {};
    profileFields.forEach((field) => {
      const control = form.elements.namedItem(field);
      if (control && "value" in control) {
        control.value = typeof values[field] === "string"
          ? formatProfileValue(field, values[field])
          : "";
      }
    });
  }

  root.StayOpsProfileForm = Object.freeze({
    fillHomeProfileForm,
    formatProfileValue,
    profileFields,
  });
})(globalThis);

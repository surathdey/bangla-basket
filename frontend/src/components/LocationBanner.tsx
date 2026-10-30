import React, { useEffect, useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, Platform } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { api } from "@/src/api";
import { usePricingLocation } from "@/src/location";
import { colors, spacing } from "@/src/theme";

/**
 * "Your location detected — <City>" banner.
 *
 * Shown at the top of the customer app + website ONLY when the admin has
 * enabled it (Admin → Settings → "Location detected banner"). Primarily a
 * QA/testing aid to confirm expo-location / browser geolocation is working.
 *
 * `topInset` lets the caller push the banner below the status bar / notch.
 */
export function LocationBanner({ topInset = 0, enabled: enabledProp }: { topInset?: number; enabled?: boolean }) {
  const { city, fsa, ready, postal, showHelp } = usePricingLocation();
  const [enabledSelf, setEnabledSelf] = useState(false);

  useEffect(() => {
    if (enabledProp !== undefined) return; // parent controls it
    (async () => {
      const r = await api.get<{ location_banner_enabled?: boolean }>("/settings");
      if (r.ok) setEnabledSelf(r.data?.location_banner_enabled === true);
    })();
  }, [enabledProp]);

  const enabled = enabledProp !== undefined ? enabledProp : enabledSelf;
  if (!enabled) return null;

  // Detection finished but no location (denied / failed) → actionable prompt.
  // Only grocery prices are gated — meal-plan prices are always visible — so the
  // copy is explicit to avoid contradicting visible meal-plan prices.
  const failed = ready && !postal;
  const verb = Platform.OS === "web" ? "click" : "tap";
  const label = city
    ? `Your location detected — ${city}`
    : failed
      ? `Location off — ${verb} to enable & see grocery prices`
      : fsa
        ? `Your location detected — ${fsa}`
        : "Detecting your location…";

  const content = (
    <>
      <Ionicons name={failed ? "location-outline" : "location"} size={14} color="#fff" />
      <Text style={styles.text} numberOfLines={1}>{label}</Text>
    </>
  );

  if (failed) {
    return (
      <TouchableOpacity style={[styles.bar, { paddingTop: topInset + 6 }]} testID="location-banner" onPress={showHelp} activeOpacity={0.8}>
        {content}
      </TouchableOpacity>
    );
  }
  return (
    <View style={[styles.bar, { paddingTop: topInset + 6 }]} testID="location-banner">
      {content}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: colors.primary,
    paddingBottom: 8,
    paddingHorizontal: spacing.lg,
  },
  text: { color: "#fff", fontSize: 12.5, fontWeight: "800", letterSpacing: 0.2 },
});

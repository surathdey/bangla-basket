import React from "react";
import { Text, TouchableOpacity, StyleSheet, View } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { usePricingLocation } from "@/src/location";
import { colors, radius } from "@/src/theme";

/**
 * Wraps a grocery price. When the customer's location is NOT detected, the
 * price is hidden and replaced with a tappable "Enable location to see the
 * price" pill that opens the how-to-enable help popup.
 *
 * `compact` renders a shorter label for small cards.
 */
export function PriceGate({ children, compact = false }: { children: React.ReactNode; compact?: boolean }) {
  const { gated, showHelp } = usePricingLocation();
  if (!gated) return <>{children}</>;
  return (
    <TouchableOpacity testID="price-gate" activeOpacity={0.8} onPress={showHelp} style={[styles.pill, compact && styles.pillCompact]}>
      <Ionicons name="location-outline" size={compact ? 12 : 14} color={colors.primary} />
      <Text style={[styles.text, compact && styles.textCompact]} numberOfLines={2}>
        {compact ? "Enable location for price" : "Enable your location to see the price"}
      </Text>
    </TouchableOpacity>
  );
}

/** True/false helper for callers that need to gate Add buttons etc. */
export function useGroceryGate() {
  const { gated, showHelp } = usePricingLocation();
  return { gated, showHelp };
}

/** A muted inline notice explaining why prices are hidden (optional use). */
export function LocationGateNotice() {
  const { gated, showHelp } = usePricingLocation();
  if (!gated) return null;
  return (
    <TouchableOpacity onPress={showHelp} style={styles.notice} testID="location-gate-notice">
      <Ionicons name="information-circle-outline" size={16} color={colors.primary} />
      <View style={{ flex: 1 }}>
        <Text style={styles.noticeText}>Enable your location to see grocery prices</Text>
      </View>
      <Ionicons name="chevron-forward" size={16} color={colors.primary} />
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    alignSelf: "flex-start",
    backgroundColor: colors.surfaceAlt,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  pillCompact: { paddingHorizontal: 8, paddingVertical: 4, gap: 3 },
  text: { color: colors.primary, fontSize: 12.5, fontWeight: "800" },
  textCompact: { fontSize: 10.5, fontWeight: "800" },
  notice: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  noticeText: { color: colors.text, fontSize: 13, fontWeight: "700" },
});

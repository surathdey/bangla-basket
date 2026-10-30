import React from "react";
import { View, Text, StyleSheet } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { colors, spacing } from "@/src/theme";

const NOTES: { label: string; text: string }[] = [
  { label: "Block", text: "Frozen fish in sealed branded packs, ready for your freezer." },
  { label: "Cut", text: "Freshly cut fish pieces, cut to your chosen weight from whole fish (without head and tail, without scale)." },
  { label: "By Weight", text: "Whole fresh fish, sold by weight — pick your size." },
];

/** Small helper note shown only on the Fresh Fish category view, explaining
 *  what each sub-category (Block / Cut / By Weight) means. */
export function FishSubcatNote({ category }: { category?: string }) {
  if (!category || !category.toLowerCase().includes("fish")) return null;
  return (
    <View style={styles.wrap} testID="fish-subcat-note">
      {NOTES.map((n) => (
        <View key={n.label} style={styles.row}>
          <Ionicons name="information-circle-outline" size={13} color={colors.textMuted} style={{ marginTop: 1 }} />
          <Text style={styles.text}>
            <Text style={styles.label}>{n.label}</Text> — {n.text}
          </Text>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: spacing.lg, paddingBottom: spacing.sm, gap: 3 },
  row: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  text: { fontSize: 12, color: colors.textMuted, lineHeight: 17, flexShrink: 1 },
  label: { fontWeight: "800", color: colors.text },
});

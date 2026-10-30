import React from "react";
import { View, StyleSheet, TouchableOpacity, Text } from "react-native";
import Ionicons from "@react-native-vector-icons/ionicons";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { useCart } from "@/src/cart";
import { colors, spacing, radius } from "@/src/theme";
import { LocationBanner } from "@/src/components/LocationBanner";
import { ProductDetailBody } from "@/src/components/ProductDetailBody";

export default function GroceryDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { count } = useCart();

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <LocationBanner topInset={insets.top} />
      <SafeAreaView edges={["top"]} style={styles.topBar}>
        <TouchableOpacity testID="grocery-back" style={styles.iconBtn} onPress={() => router.back()}>
          <Ionicons name="chevron-back" size={22} color={colors.text} />
        </TouchableOpacity>
        <TouchableOpacity testID="grocery-detail-cart" style={styles.iconBtn} onPress={() => router.push("/cart")}>
          <Ionicons name="cart-outline" size={20} color={colors.text} />
          {count > 0 && <View style={styles.cartDot}><Text style={styles.cartDotText}>{count}</Text></View>}
        </TouchableOpacity>
      </SafeAreaView>
      <ProductDetailBody id={String(id)} web={false} bottomInset={insets.bottom} />
    </View>
  );
}

const styles = StyleSheet.create({
  topBar: { flexDirection: "row", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.sm },
  iconBtn: { width: 42, height: 42, borderRadius: radius.pill, backgroundColor: colors.surface, alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.border },
  cartDot: { position: "absolute", top: 2, right: 2, minWidth: 16, height: 16, borderRadius: 8, backgroundColor: colors.primary, alignItems: "center", justifyContent: "center", paddingHorizontal: 3 },
  cartDotText: { color: "#fff", fontSize: 9, fontWeight: "800" },
});

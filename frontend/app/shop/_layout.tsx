import React from "react";
import { Stack } from "expo-router";

export default function ShopLayout() {
  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Screen name="index" />
      <Stack.Screen name="browse" />
      <Stack.Screen name="meal-plans" />
      <Stack.Screen name="account" />
      <Stack.Screen name="reset-password" />
      <Stack.Screen name="cart" />
      <Stack.Screen name="order/[id]" />
      <Stack.Screen name="product/[id]" />
      <Stack.Screen name="thali" />
    </Stack>
  );
}

class PricingCalculator:
    @staticmethod
    def calculate(category, subtotal, shipping):
        if category == "premium":
            discount = subtotal * 10 // 100
        elif category == "business":
            discount = subtotal * 15 // 100
        else:
            discount = 0
        if shipping == "pickup":
            delivery = 0
        elif shipping == "standard":
            delivery = 0 if subtotal >= 10_000 else 1_000
        else:
            delivery = 2_500
        total = subtotal - discount + delivery
        return discount, delivery, total

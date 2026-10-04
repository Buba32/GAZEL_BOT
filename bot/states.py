from aiogram.fsm.state import State, StatesGroup


class OrderForm(StatesGroup):
    src = State()  # ждём адрес «откуда»
    dst = State()  # ждём адрес «куда»
    confirm = State()  # показали расчёт, ждём подтверждения

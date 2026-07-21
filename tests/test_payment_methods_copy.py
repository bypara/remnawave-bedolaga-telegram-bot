from app.utils import payment_utils


def test_payment_methods_copy_is_compact(monkeypatch):
    monkeypatch.setattr(
        payment_utils,
        'get_available_payment_methods',
        lambda: [
            {
                'id': 'stars',
                'name': 'Telegram Stars',
                'icon': '⭐',
                'description': 'быстро и удобно',
                'callback': 'topup_stars',
            }
        ],
    )

    rendered = payment_utils.get_payment_methods_text('ru')

    assert '5258204546391351475' in rendered
    assert 'Способы пополнения баланса' in rendered
    assert 'Выберите удобный для вас способ оплаты:' not in rendered
    assert 'Telegram Stars' not in rendered
    assert 'Выберите способ пополнения:' not in rendered
    assert not rendered.endswith('\n')

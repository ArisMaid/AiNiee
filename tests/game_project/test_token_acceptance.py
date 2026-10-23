import unittest
from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy


class TokenAcceptance(unittest.TestCase):
    def test_repeated_control_is_preserved(self):
        p = TokenPolicy(['nbx', 'TE', 'CR'])
        source = r'\nbx[1]\C[9]保存\C[9] \n[1]\TE'
        protected = p.protect(source, 'u1')
        self.assertFalse(protected.issues)
        translated, issues = protected.restore(protected.text.replace('保存', '存档'))
        self.assertFalse(issues)
        self.assertFalse(p.validate(source, translated))
        self.assertIn('存档', translated)

    def test_malformed_or_invented_code_is_blocked(self):
        p = TokenPolicy()
        self.assertTrue(p.scan(r'\V[2')[1])
        self.assertTrue(p.scan(r'\unknown[1]')[1])
        self.assertTrue(p.validate(r'\V[2]内容', r'\V[3]内容'))
        protected = p.protect(r'\V[2]内容')
        self.assertTrue(protected.restore(protected.text + r'\V[3]')[1])
        self.assertTrue(protected.restore(protected.text + protected.markers[0])[1])

    def test_actual_newline_is_not_name_control(self):
        p = TokenPolicy()
        self.assertEqual(len(p.scan('第一行\n第二行')[0]), 0)
        self.assertEqual(len(p.scan(r'\n[1]第二行')[0]), 1)

    def test_runtime_template_arguments(self):
        p=TokenPolicy()
        self.assertEqual(len(p.scan('获得 %1 个 {item}。')[0]),2)
        self.assertTrue(p.validate('获得 %1 个 {item}。','获得 %2 个 {item}。'))
        protected=p.protect('获得 %1 个 {item}。')
        restored,issues=protected.restore(protected.text)
        self.assertFalse(issues)
        self.assertEqual(restored,'获得 %1 个 {item}。')

    def test_choice_conditions_are_protected_as_complete_logic(self):
        policy=TokenPolicy()
        for source in [r'選択肢\en(v[999] >= 999)','選択肢 en(v[1] > 3) if(s[2])']:
            with self.subTest(source=source):
                protected=policy.protect(source)
                self.assertFalse(protected.issues)
                self.assertNotIn('v[',protected.text)
                restored,issues=protected.restore(protected.text.replace('選択肢','选项'))
                self.assertFalse(issues)
                self.assertFalse(policy.validate(source,restored))
                self.assertTrue(policy.validate(source,restored.replace('v[','v[9')))


if __name__ == '__main__':
    unittest.main()

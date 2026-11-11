"""No model is called; test only the blind-input contract."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('prediction_bridge',Path(__file__).with_name('predict-frozen.py'))
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
class BridgeTests(unittest.TestCase):
    def load(self,rows):
        task_root=Path(__file__).resolve().parent.parent/'.work'
        task_root.mkdir(exist_ok=True)
        directory=Path(tempfile.mkdtemp(prefix='prediction-input-test-',dir=task_root))
        file=directory/'template.json';file.write_text(json.dumps({'dataset_sha256':'a'*64,'requests':rows}),encoding='utf-8')
        return bridge.load_template(file)
    def row(self):return {'case_id':'software-test','policy_id':'policy','profile':{'degree':None},'clauses':[{'id':'clause','text':'test fixture'}],'allowed_materials':[]}
    def test_input_does_not_include_reference_labels(self):
        row=self.load([self.row()])['requests'][0]
        content=json.loads(bridge.messages_for(row)[1]['content'])
        self.assertEqual(set(content),{'policy_id','applicant','clauses','allowed_materials'})
    def test_gold_labels_are_refused(self):
        row=self.row();row['expected']={'conclusion':'insufficient'}
        with self.assertRaisesRegex(ValueError,'人工答案'):self.load([row])
    def test_duplicate_case_numbers_are_refused(self):
        with self.assertRaisesRegex(ValueError,'重复'):self.load([self.row(),self.row()])

if __name__=='__main__':unittest.main()

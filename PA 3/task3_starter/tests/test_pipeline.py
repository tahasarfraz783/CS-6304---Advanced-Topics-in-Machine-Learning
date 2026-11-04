import tempfile
from pathlib import Path
import pickle
import unittest
import numpy as np
import pandas as pd
from task3.common import write,read
from task3.data import qpath
from task3.core import orders_for
from task3.offline import one_question,aggregate
from task3.evidence import build
from task3.live import live_summary


class DummyProgress:
    def update(self,*args):pass


class Pipeline(unittest.TestCase):
    def test_offline_aggregation_recovery_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for dataset in ['MATH','MathVista']:
                split={'dev':['d0','d1'],'eval':['e0','e1'],'live':[]}
                write(root/'splits'/f'{dataset}.json',split)
                for sid in split['dev']+split['eval']:
                    cs=[]
                    for j in range(32):
                        c=dict(id=j,answer='A' if j<24 else 'B',correct=j<24,tokens=2,
                               L=-1.,K=float(j),kl=np.array([float(j),float(j+1)]),
                               text='example',extracted='A' if j<24 else 'B')
                        if dataset=='MathVista':c['v']=np.array([.2,.8])
                        cs.append(c)
                    q=dict(dataset=dataset,sample_id=sid,question='synthetic question',gold='A',candidates=cs,orders=orders_for(0))
                    path=qpath(root,dataset,sid);path.parent.mkdir(parents=True,exist_ok=True)
                    with path.open('wb') as f:pickle.dump(q,f)
                    one_question((root,dataset,sid))
                    target=root/'offline'/dataset/(sid+'.json');before=target.read_bytes()
                    one_question((root,dataset,sid));self.assertEqual(before,target.read_bytes())
            aggregate(root,DummyProgress());build(root)
            comparison=pd.read_csv(root/'evidence'/'method_comparison.csv')
            first=comparison[comparison.method=='FirstAns'];self.assertTrue((first.tokens==2).all())
            sc=comparison[comparison.method=='SC'];self.assertTrue((sc.tokens==sc.N*2).all())
            self.assertTrue((root/'evidence'/'index.html').exists())
            self.assertTrue((root/'evidence'/'MATH_accuracy_cost.png').exists())
            self.assertEqual(len(read(root/'evidence'/'adaptive_summary.json')),4)
    def test_live_shared_initial_cost_and_revision_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);write(root/'splits'/'MATH.json',{'live':['test:1']})
            q={'gold':'2'};path=qpath(root,'MATH','test:1');path.parent.mkdir(parents=True)
            with path.open('wb') as f:pickle.dump(q,f)
            for name in ['parallel_0','parallel_1','parallel_2','long','revision']:
                write(root/'live'/'calls'/f'00_{name}.json',dict(extracted='1' if name=='parallel_0' else '2',
                      input_tokens=10,output_tokens=20,retained_tokens=19,seconds=1.,truncated=False,peak_allocated_bytes=100))
            live_summary(root)
            df=pd.read_csv(root/'evidence'/'live_per_question.csv').set_index('strategy')
            self.assertEqual(df.loc['parallel','output_tokens'],60)
            self.assertEqual(df.loc['refinement','output_tokens'],40)
            self.assertEqual(df.loc['refinement','seconds'],2)
            self.assertTrue(df.loc['refinement','wrong_to_correct'])


if __name__=='__main__':unittest.main()

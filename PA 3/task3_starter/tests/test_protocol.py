import unittest
import numpy as np
from task3.core import boxed,votes,rwc,quality,select,stopping,split_ids,orders_for,NO_ANSWER
from task3.scoring import group_and_grade,math_equal,vista,parsed


def candidate(answer,kl=(1.,2.),v=None):
    c=dict(answer=answer,L=-1.,K=float(np.mean(kl)),kl=np.array(kl),tokens=len(kl))
    if v is not None:c['v']=np.array(v)
    return c


class Protocol(unittest.TestCase):
    def test_boxed_last_balanced(self):
        self.assertEqual(boxed(r'\boxed{2} then \boxed{\frac{1}{2}}'),r'\frac{1}{2}')
        self.assertIsNone(boxed(r'\boxed{2} then \boxed{bad'))
        self.assertIsNone(boxed(r'\boxed{}'))
    def test_ties_and_missing(self):
        self.assertEqual(votes(['B','A','A','B'])[0],'B')
        self.assertEqual(votes([NO_ANSWER,NO_ANSWER,'A'])[0],NO_ANSWER)
        self.assertEqual(rwc(['B','A'],[1.,1.])[0],'B')
    def test_average_rank(self):
        # tied best both get .75, worst gets zero.
        winner,margin=rwc(['X','Y','Y'],[2,2,1])
        self.assertEqual(winner,'X');self.assertEqual(margin,0)
    def test_prefix_calibration_and_covariance(self):
        cs=[candidate('A',(1.,2.),(.2,.8)),candidate('B',(3.,4.),(.1,.9))]
        scores=quality(cs);lo,hi=np.quantile([1,2,3,4],[.05,.95],method='linear')
        conf=np.clip((cs[0]['kl']-lo)/(hi-lo),0,1)
        self.assertAlmostEqual(scores['visconf'][0],conf.mean()*.5)
        self.assertAlmostEqual(scores['tokenfusion'][0]-scores['visconf'][0],np.mean(conf*cs[0]['v'])-conf.mean()*cs[0]['v'].mean())
        before=quality(cs)['visconf'].copy()
        future=candidate('C',(1000.,2000.),(.5,.5))
        quality(cs+[future])
        np.testing.assert_array_equal(quality(cs)['visconf'],before)
    def test_single_candidate_all_return_it(self):
        self.assertEqual(set(select([candidate('A',v=(.1,.9))]).values()),{'A'})
    def test_stopping(self):
        cs=[candidate(a) for a in ['A','A','A','B']]
        self.assertTrue(stopping(cs,'agreement',.75,0,np.ones(4)))
        self.assertFalse(stopping(cs,'agreement',.875,0,np.ones(4)))
        self.assertFalse(stopping([candidate(NO_ANSWER)]*4,'agreement',.5,0,np.ones(4)))
        self.assertFalse(stopping([candidate(a) for a in ['A','A','B','B']],'agreement',.5,0,np.ones(4)))
    def test_split_and_orders(self):
        split=split_ids([str(i) for i in range(1000)])
        self.assertEqual(len(split['dev']),200);self.assertEqual(len(split['eval']),800)
        self.assertEqual(split['live'],split['eval'][:50]);self.assertFalse(set(split['dev'])&set(split['eval']))
        for order in orders_for(3):self.assertEqual(sorted(order),list(range(32)))
        self.assertEqual(orders_for(3),orders_for(3));self.assertNotEqual(orders_for(3),orders_for(4))
    def test_math_equivalence(self):
        self.assertTrue(math_equal('0.5',r'\frac{1}{2}'))
        self.assertFalse(math_equal('2','3'))
        groups,correct=group_and_grade(['0.5',r'\frac{1}{2}',None],'0.5','MATH')
        self.assertEqual(groups[0],groups[1]);self.assertEqual(correct,[True,True,False])
        a,_=group_and_grade(['2','3'],'2','MATH');b,_=group_and_grade(['2','3'],'3','MATH')
        self.assertEqual(a,b)
    def test_symbolic_objects_stay_in_isolated_worker(self):
        # Reconstructing this expression in a parent process can eagerly expand
        # a giant power. The public IPC result must remain a primitive boolean.
        self.assertIsInstance(parsed(r'(2+\sqrt{2})^{3^{100}}'),bool)
        self.assertTrue(math_equal('1','1'))
    def test_vista(self):
        mc=dict(question_type='multi_choice',answer_type='text',choices=['cat','dog'])
        self.assertEqual(vista('(B) dog',mc),'B');self.assertEqual(vista('dog',mc),'B')
        self.assertEqual(vista(None,mc),NO_ANSWER)
        number=dict(question_type='free_form',answer_type='float',precision=2)
        self.assertEqual(vista('1.234',number),'1.23')


if __name__=='__main__':unittest.main()

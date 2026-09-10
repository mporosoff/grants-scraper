import unittest
try:
    import numpy as np
    from scipy.special import expit,roots_hermite
    from scipy.optimize import brentq
    from tools.team_recommender_learning import fit_logistic,compare
    AVAILABLE=True
except ImportError:
    AVAILABLE=False

@unittest.skipUnless(AVAILABLE,'Optional offline evaluation dependencies; never a production runtime dependency')
class LearningReferenceTests(unittest.TestCase):
    def test_intercept_solution_agrees_with_independent_scalar_root(self):
        a=np.ones((10,1));target=np.array([1]*3+[0]*7);penalty=np.array([.04])
        beta,h,gradient,success,iterations=fit_logistic(a,target,penalty)
        expected=brentq(lambda b:10*expit(b)-3+.04*b,-20,20)
        self.assertAlmostEqual(beta[0],expected,places=7)
        self.assertTrue(success);self.assertLess(gradient,1e-7);self.assertLess(iterations,80);self.assertGreater(h[0,0],0)

    def test_laplace_predictive_integration_has_correct_symmetry_and_zero_variance(self):
        nodes,weights=roots_hermite(20)
        def predictive(mu,variance):return float(np.sum(weights*expit(mu+np.sqrt(2*variance)*nodes))/np.sqrt(np.pi))
        for variance in (0,.1,1,4):self.assertAlmostEqual(predictive(0,variance),.5,places=12)
        self.assertAlmostEqual(predictive(1,0),float(expit(1)),places=12)
        self.assertLess(predictive(1,1),predictive(1,0))

    def test_insufficient_labels_are_neither_positive_nor_negative_and_cannot_claim_fitting(self):
        items=[{'label':'insufficient-information','group_id':str(i)} for i in range(25)]
        report=compare(items)
        self.assertEqual(report['binary_usable'],0);self.assertEqual(report['insufficient_information'],25)
        self.assertEqual(report['models'],[])

if __name__=='__main__':unittest.main()

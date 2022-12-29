"""
Basic class agnostic counting model with backbone, refiner, matcher and counter.
"""
import torch
from torch import nn

class CACModel(nn.Module):
    """ Class Agnostic Counting Model"""
    
    def __init__(self, backbone, EPF_extractor, refiner, matcher, counter, hidden_dim):
        """ Initializes the model.
        Parameters:
            backbone: torch module of the backbone to be used. See backbone.py
            EPF_extractor: torch module of the feature extractor for patches. See epf_extractor.py
            repeat_times: Times to repeat each exemplar in the transformer decoder, i.e., the features of exemplar patches.
        """
        super().__init__()
        self.EPF_extractor = EPF_extractor
        self.refiner = refiner
        self.matcher = matcher
        self.counter = counter

        self.backbone = backbone
        self.hidden_dim = hidden_dim
        self.input_proj = nn.Conv2d(backbone.num_channels, hidden_dim, kernel_size=1)
        
    def forward(self, samples: torch.Tensor, patches: torch.Tensor, is_train: bool):
        """ The forward expects samples containing query images and corresponding exemplar patches.
            samples is a stack of query images, of shape [batch_size X 3 X H X W]
            patches is a torch Tensor, of shape [batch_size x num_patches x 3 x 128 x 128]
            The size of patches are small than samples

            It returns a dict with the following elements:
               - "density_map": Shape= [batch_size x 1 X h_query X w_query]
               - "patch_feature": Features vectors for exemplars, not available during testing.
                                  They are used to compute similarity loss. 
                                Shape= [exemplar_number x bs X hidden_dim]
               - "img_feature": Feature maps for query images, not available during testing.
                                Shape= [batch_size x hidden_dim X h_query X w_query]
            
        """
        # Stage 1: extract features for query images and exemplars
        scale_embedding, patches = patches['scale_embedding'], patches['patches']
        features = self.backbone(samples)
        features = self.input_proj(features)
        
        patches = patches.flatten(0, 1) 
        patch_feature = self.backbone(patches) # obtain feature maps for exemplar patches
        ####################################################################################################
        # feat_aug_list [tensor([1., 0., 0.]), tensor([0., 1., 0.]), tensor([0., 0., 1.])]
        # 特征增强模块
        feat_aug_list = []
        tt = torch.zeros(3, 3)
        for i in range(3):
            tt[i, i] = 1.0
            feat_aug_list.append(tt[i])

        new_list = []
        for temp in feat_aug_list:
            if torch.sum(temp) == 0:
                continue
            new_list.append(temp / torch.sum(temp))

        feat_aug_list = new_list
        aug_patch_feature = torch.zeros(len(feat_aug_list), patch_feature.shape[1], patch_feature.shape[2],
                                        patch_feature.shape[3]).cuda()
        for i in range(len(feat_aug_list)):
            for j in range(feat_aug_list[0].shape[0]):
                aug_patch_feature[i] += feat_aug_list[i][j] * patch_feature[j]
        #将特征图压缩成矢量并注入比例嵌入(通过相应的尺度嵌入来增强样本的特征)
        # patch_feature = self.EPF_extractor(patch_feature, scale_embedding) # compress the feature maps into vectors and inject scale embeddings
        patch_feature = self.EPF_extractor(aug_patch_feature,scale_embedding)  # compress the feature maps into vectors and inject scale embeddings
        ####################################################################################################
        # Stage 2: enhance feature representation, e.g., the self similarity module.
        #增强特征表示，例如自相似模块。
        refined_feature, patch_feature = self.refiner(features, patch_feature)
        # Stage 3: generate similarity map by densely measuring similarity.
        counting_feature, corr_map = self.matcher(refined_feature, patch_feature)
        # Stage 4: predicting density map 
        density_map = self.counter(counting_feature)
        
        if not is_train:
            return density_map
        else:
            return {'corr_map': corr_map, 'density_map': density_map}

    #def _reset_parameters(self):
    #    for p in self.parameters():
    #        if p.dim() > 1:
    #            nn.init.xavier_uniform_(p)

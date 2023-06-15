# Counts dots present in nucleus and cell
# Save an image showing what the model counted so researcher can finish
# More sophisticated quilting

import numpy as np
import random
import torch
import torchvision
import cv2
import cv2 as cv
from src.nodes.AbstractNode import AbstractNode
from segment_anything import sam_model_registry, SamAutomaticMaskGenerator, SamPredictor
import src.image_processing as ip
import src.sam_processing as sp
import os

class SamCellDotCounter(AbstractNode):
    def __init__(self):
        from src.fishnet import FishNet
        super().__init__(output_name="SamDotCountPack",
                         requirements=["ManualCellMaskPack"],
                         user_can_retry=False,
                         node_title="Auto SAM Cell Dot Counter")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.save_folder = "particle_segmentations/"
        self.max_pix_area = 1024*1024
        self.quilt_factor = 4
        self.block_size = 512
        self.base_img = None
        self.sam_mask_generator = None
        self.sam = None
        self.sam_predictor = None
        self.cyto_id_mask = None
        self.nuc_id_mask = None
        self.cytoplasm_key = "cyto"
        self.nucleus_key = "nuc"
        self.cell_id_mask = None
        self.csv_name =  "dot_counts.csv"
        self.nuc_counts = {}
        self.cyto_counts = {}
        self.seg_imgs = {}
        self.raw_crop_imgs = {}
        save_folder = FishNet.save_folder + self.save_folder
        self.prog = 0.00
        if not os.path.exists(save_folder):
            os.makedirs(save_folder)

    def setup_sam(self):
        sam_checkpoint = "sam_model/sam_vit_h_4b8939.pth"
        model_type = "vit_h"
        self.sam = sam_model_registry[model_type](checkpoint=sam_checkpoint)
        self.sam.to(device=self.device)
        default_sam_settings = {
                    "points_per_side": 32, #32
                    "pred_iou_thresh": 0.5, #0.5
                    "stability_score_thresh": 0.95, #0.85
                    "crop_n_layers": 1, #1
                    "crop_n_points_downscale_factor": 2,
                    "min_mask_region_area": 1 }
        self.mask_generator = SamAutomaticMaskGenerator(model=self.sam, **default_sam_settings)


    def initialize_node(self):
        # Image Prep?
        raw_img = ip.get_all_mrna_img()
        self.base_img = ip.preprocess_img2(raw_img)
        self.get_id_mask()
        self.setup_sam()

    def get_id_mask(self):
        from src.fishnet import FishNet
        mask_pack = FishNet.pipeline_output["ManualCellMaskPack"]
        self.cyto_id_mask = mask_pack["cytoplasm"]
        self.nuc_id_mask = mask_pack["nucleus"]
        self.cell_id_mask = {
            self.cytoplasm_key: self.cyto_id_mask,
            self.nucleus_key: self.nuc_id_mask
        }
        

    def save_output(self):
        self.save_dot_count_csv()
        self.save_segs()

    def process(self):
        self.process_cell_part(self.cytoplasm_key)
        self.process_cell_part(self.nucleus_key)
        # self.process_cytos()
        # self.process_nucs()
        self.set_node_as_successful()

    def save_dot_count_csv(self):
        from src.fishnet import FishNet
        # csv of particle counts
        particle_csv = FishNet.save_folder + self.csv_name
        csv_file = open(particle_csv, "w")
        csv_file.write("cell_id,cyto_counts,nuc_counts\n")
        for nuc_id in self.nuc_counts.keys():
            if nuc_id in self.cyto_counts:
                obs = str(nuc_id) + "," + str(self.cyto_counts[nuc_id]) + "," + str(self.nuc_counts[nuc_id])
                csv_file.write(obs)
        csv_file.write("\n")
        csv_file.close()

    def save_segs(self):
        for save_name in self.seg_imgs:
            img_path = self.save_folder + save_name
            self.save_img(self.seg_imgs[save_name], img_path)
        for save_name in self.raw_crop_imgs:
            img_path = self.save_folder + save_name
            self.save_img(self.raw_crop_imgs[save_name], img_path)

    def process_cell_part(self, cell_part):
        print(f"Processing {cell_part}...")
        id_mask = self.cell_id_mask[cell_part]
        cell_ids = np.unique(id_mask)
        print(f"Percent Done: 0.00%")
        for cell_id in cell_ids:
            if cell_id == 0:
                continue

            targ_shape = self.base_img.shape
            id_activation = np.where(id_mask == cell_id, 1, 0)
            resized_id_activation = id_activation[:, :, np.newaxis]
            resized_id_activation = ip.resize_img(
                resized_id_activation,
                targ_shape[0],
                targ_shape[1],
                inter_type="linear")
            resized_id_activation = resized_id_activation[:, :, np.newaxis]
            id_bbox = self.get_segmentation_bbox(id_activation)
            id_bbox = ip.rescale_boxes(
                [id_bbox],
                id_activation.shape,
                self.base_img.shape)[0]
            xmin = int(id_bbox[0])
            xmax = int(id_bbox[2])
            ymin = int(id_bbox[1])
            ymax = int(id_bbox[3])
            img_id_activated = resized_id_activation * self.base_img
            img_crop = img_id_activated[ymin:ymax, xmin:xmax, :].copy()
            # img_crop = ip.resize_img_to_pixel_size(img_crop, self.max_pix_area)
            img_crop = ip.resize_img(img_crop, 1024, 1024)
            # Might be problematic to do this
            img_crop = np.where(img_crop == 0, random.randint(0, 254), img_crop)

            dot_count = None
            seg = None
            if self.quilt_factor < 2:
                dot_count, seg = self.get_dot_count_and_seg_pure(img_crop.copy())
            elif self.quilt_factor >= 2:
                dot_count, seg = self.get_dot_count_and_seg_quilt(img_crop.copy())
            if cell_part == self.cytoplasm_key:
                self.cyto_counts[cell_id] = dot_count
            elif cell_part == self.nucleus_key:
                self.nuc_counts[cell_id] = dot_count
            self.store_segmentation(cell_part, cell_id, img_crop, seg)
            if cell_part == self.cytoplasm_key:
                self.store_raw_crop(id_bbox, cell_id)

            percent_done = cell_id / (len(cell_ids)-1)*100
            print(f"Percent Done: {percent_done:.2f}%")

    def process_cytos(self):
        cyto_ids = np.unique(self.cyto_id_mask)
        for cyto_id in cyto_ids:
            if cyto_id == 0:
                continue
            targ_shape = self.base_img.shape
            id_activation = np.where(self.cyto_id_mask == cyto_id, 1, 0)
            resized_id_activation = id_activation[:, :, np.newaxis]
            resized_id_activation = ip.resize_img(
                resized_id_activation,
                targ_shape[0],
                targ_shape[1],
                inter_type="linear")
            resized_id_activation = resized_id_activation[:, :, np.newaxis]
            id_bbox = self.get_segmentation_bbox(id_activation)
            id_bbox = ip.rescale_boxes(
                [id_bbox],
                id_activation.shape,
                self.base_img.shape)[0]
            xmin = int(id_bbox[0])
            xmax = int(id_bbox[2])
            ymin = int(id_bbox[1])
            ymax = int(id_bbox[3])
            img_id_activated = resized_id_activation * self.base_img
            img_crop = img_id_activated[ymin:ymax, xmin:xmax, :].copy()
            img_crop = ip.resize_img(img_crop, 1024, 1024)
            dot_count, seg = self.get_dot_count_and_seg(img_crop.copy())
            self.cyto_counts[cyto_id] = dot_count
            self.store_segmentation("cyto", cyto_id, img_crop, seg)
            self.store_raw_crop(id_bbox, cyto_id)

    def store_raw_crop(self, id_bbox, cell_id):
        base_shape = self.base_img.shape
        pad = 20
        xmin = int(id_bbox[0] - pad)
        xmax = int(id_bbox[2] + pad)
        ymin = int(id_bbox[1] - pad)
        ymax = int(id_bbox[3] + pad)
        if xmin < 0:
            xmin = 0
        if ymin < 0:
            ymin = 0
        if xmax >= base_shape[1]:
            xmax = base_shape[1]-1
        if ymax >= base_shape[0]:
            ymax = base_shape[0] - 1
        save_name = f"c{cell_id}_raw.png"
        self.raw_crop_imgs[save_name] = self.base_img[ymin:ymax, xmin:xmax, :].copy()
        

    def process_nucs(self):
        nuc_ids = np.unique(self.nuc_id_mask)
        for nuc_id in nuc_ids:
            if nuc_id == 0:
                continue
            targ_shape = self.base_img.shape
            id_activation = np.where(self.nuc_id_mask == nuc_id, 1, 0)
            resized_id_activation = id_activation[:, :, np.newaxis]
            resized_id_activation = ip.resize_img(
                resized_id_activation,
                targ_shape[0],
                targ_shape[1],
                inter_type="linear")
            resized_id_activation = resized_id_activation[:, :, np.newaxis]
            id_bbox = self.get_segmentation_bbox(id_activation)
            id_bbox = ip.rescale_boxes(
                [id_bbox],
                id_activation.shape,
                self.base_img.shape)[0]
            xmin = int(id_bbox[0])
            xmax = int(id_bbox[2])
            ymin = int(id_bbox[1])
            ymax = int(id_bbox[3])
            img_id_activated = resized_id_activation * self.base_img
            img_crop = img_id_activated[ymin:ymax, xmin:xmax, :].copy()
            img_crop = ip.resize_img(img_crop, 1024, 1024)
            dot_count, seg = self.get_dot_count_and_seg(img_crop.copy())
            self.nuc_counts[nuc_id] = dot_count
            self.store_segmentation("nuc", nuc_id, img_crop, seg)

    def store_segmentation(self, cell_part, cell_id, orig_img, segmentation):
        img_overlay = orig_img*0.7 + segmentation*0.3
        save_name = f"cell{cell_id}_{cell_part}.png"
        self.seg_imgs[save_name] = img_overlay
        

    def get_segmentation_bbox(self, single_id_mask):
        gray = single_id_mask[:, :, np.newaxis].astype(np.uint8)
        contours, hierarchy = cv2.findContours(gray,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)[-2:]
        idx =0 
        rois = []
        largest_area = 0
        best_bbox = []
        first = True
        for cnt in contours:
            idx += 1
            area = cv.contourArea(cnt)
            rect_pack = cv2.boundingRect(cnt) #x, y, w, h
            x, y, w, h = rect_pack
            bbox = [x, y, x+w, y+h]
            if first:
                first = False
                largest_area = area
                best_bbox = bbox
            else:
                if area > largest_area:
                    largest_area = area
                    best_bbox = bbox
        return best_bbox

    def get_dot_count_and_seg_quilt(self, img_subset):
        img_seq = self.get_image_seq(img_subset, self.block_size)
        seg_seq, dot_count = self.get_dot_count_and_seg_seq(img_seq)
        restored_seg = self.coalesce_img_seq(img_subset, seg_seq, self.block_size)
        return dot_count, restored_seg

    def get_dot_count_and_seg_pure(self, img_subset):
        mask = self.mask_generator.generate(img_subset)
        mask_img, dot_count = self.process_sam_mask(img_subset, mask)
        seg = ip.generate_single_colored_mask(mask_img)
        return dot_count, seg

    def coalesce_img_seq(self, img, img_seq, block_size):
        x_imgs = int(img.shape[0]/block_size)
        y_imgs = int(img.shape[1]/block_size)
        i = 0
        for x_img in range(x_imgs):
            for y_img in range(y_imgs):
                start_x = x_img*block_size
                start_y = y_img*block_size
                end_x = x_img*block_size + block_size
                end_y = y_img*block_size + block_size
                img[start_x:end_x, start_y:end_y, :] = img_seq[i].astype(int)
                i += 1
        return img

    def get_image_seq(self, img, block_size):
        img_seq = []
        x_imgs = int(img.shape[0]/block_size)
        y_imgs = int(img.shape[1]/block_size)
        for x_img in range(x_imgs):
            for y_img in range(y_imgs):
                start_x = x_img*block_size
                start_y = y_img*block_size
                end_x = x_img*block_size + block_size
                end_y = y_img*block_size + block_size
                img_seq.append(img[start_x:end_x, start_y:end_y])
        return img_seq

    def get_dot_count_and_seg_seq(self, img_seq):
        seg_seq = []
        total_dot_count = 0

        prog = 0
        for img in img_seq:
            prog += 1
            print(prog)
            masks = self.mask_generator.generate(img)
            mask_img, dot_counts = self.process_sam_mask(img, masks)
            total_dot_count += dot_counts
            seg = ip.generate_single_colored_mask(mask_img)
            seg_seq.append(seg)
        return seg_seq, total_dot_count

    def process_sam_mask(self, img, sam_mask):
        mask_shape = (img.shape[0], img.shape[1])
        mask_img = np.zeros(mask_shape)
        total_pix = np.sum(np.ones(mask_shape))
        instance_id = 0
        for m in sam_mask:
                mask_sum = np.sum(m["segmentation"])
                if mask_sum/total_pix > 0.05:
                    continue
                instance_id += 1
                mask_instance = np.zeros(mask_shape)
                segment_instance = np.where(m["segmentation"] == True, instance_id, 0)
                mask_instance += segment_instance
                mask_img += mask_instance
        return mask_img, instance_id
